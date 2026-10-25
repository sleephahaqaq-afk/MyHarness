"""记忆存储后端抽象。

基座不绑定任何具体数据库：只要满足 :class:`MemoryBackend` 协议即可替换。
默认提供两种实现：

- :class:`InMemoryBackend`：进程内，测试与单机默认；
- :class:`FileBackend`：JSON 落盘，便于本地重启后仍保留记忆。

如需接 LangGraph 官方 Store（SQLite / Redis / Postgres），用
:class:`LangGraphStoreAdapter` 同步包装其 async 接口即可。
"""
from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class MemoryRecord:
    """后端返回的一条记录。"""

    namespace: Tuple[str, ...]
    key: str
    value: Dict[str, Any]
    created_at: str = ""
    updated_at: str = ""


def _ns_key(namespace: Sequence[str]) -> Tuple[str, ...]:
    return tuple(str(p) for p in namespace)


class MemoryBackend:
    """记忆后端协议（同步接口）。"""

    def get(self, namespace: Sequence[str], key: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def put(self, namespace: Sequence[str], key: str, value: Dict[str, Any]) -> None:
        raise NotImplementedError

    def delete(self, namespace: Sequence[str], key: str) -> None:
        raise NotImplementedError

    def search(
        self, namespace: Sequence[str], *, limit: int = 100, offset: int = 0
    ) -> List[MemoryRecord]:
        raise NotImplementedError

    def namespaces(self, prefix: Sequence[str] = ()) -> List[Tuple[str, ...]]:
        raise NotImplementedError


class InMemoryBackend(MemoryBackend):
    """进程内后端，线程安全。"""

    def __init__(self) -> None:
        self._data: Dict[Tuple[str, ...], Dict[str, Dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def get(self, namespace, key):
        with self._lock:
            bucket = self._data.get(_ns_key(namespace), {})
            value = bucket.get(key)
            return dict(value) if isinstance(value, dict) else None

    def put(self, namespace, key, value):
        with self._lock:
            self._data.setdefault(_ns_key(namespace), {})[key] = dict(value)

    def delete(self, namespace, key):
        with self._lock:
            bucket = self._data.get(_ns_key(namespace))
            if bucket:
                bucket.pop(key, None)

    def search(self, namespace, *, limit=100, offset=0):
        with self._lock:
            bucket = self._data.get(_ns_key(namespace), {})
            items = list(bucket.items())[offset : offset + limit]
        return [
            MemoryRecord(namespace=_ns_key(namespace), key=k, value=dict(v))
            for k, v in items
        ]

    def namespaces(self, prefix=()):
        head = _ns_key(prefix)
        with self._lock:
            return [ns for ns in self._data if ns[: len(head)] == head]


class FileBackend(MemoryBackend):
    """JSON 文件后端（原子写：临时文件 + replace）。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(raw, dict):
            for ns, bucket in raw.items():
                if isinstance(bucket, dict):
                    self._data[tuple(ns.split("\x1f"))] = {
                        str(k): v for k, v in bucket.items() if isinstance(v, dict)
                    }

    def _flush(self) -> None:
        payload = {"\x1f".join(ns): bucket for ns, bucket in self._data.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, namespace, key):
        with self._lock:
            value = self._data.get(_ns_key(namespace), {}).get(key)
            return dict(value) if isinstance(value, dict) else None

    def put(self, namespace, key, value):
        with self._lock:
            self._data.setdefault(_ns_key(namespace), {})[key] = dict(value)
            self._flush()

    def delete(self, namespace, key):
        with self._lock:
            bucket = self._data.get(_ns_key(namespace))
            if bucket and key in bucket:
                bucket.pop(key)
                self._flush()

    def search(self, namespace, *, limit=100, offset=0):
        with self._lock:
            bucket = self._data.get(_ns_key(namespace), {})
            items = list(bucket.items())[offset : offset + limit]
        return [MemoryRecord(namespace=_ns_key(namespace), key=k, value=dict(v)) for k, v in items]

    def namespaces(self, prefix=()):
        head = _ns_key(prefix)
        with self._lock:
            return [ns for ns in self._data if ns[: len(head)] == head]


class LangGraphStoreAdapter(MemoryBackend):
    """把 LangGraph ``BaseStore``（async）适配成同步后端。

    在已有事件循环中会切到独立线程执行，避免 ``asyncio.run`` 嵌套报错。
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    @staticmethod
    def _run(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    def get(self, namespace, key):
        async def _call():
            return await self._store.aget(_ns_key(namespace), key)

        item = self._run(_call())
        return dict(item.value) if item is not None else None

    def put(self, namespace, key, value):
        async def _call():
            await self._store.aput(_ns_key(namespace), key, dict(value))

        self._run(_call())

    def delete(self, namespace, key):
        async def _call():
            await self._store.adelete(_ns_key(namespace), key)

        self._run(_call())

    def search(self, namespace, *, limit=100, offset=0):
        async def _call():
            return await self._store.asearch(_ns_key(namespace), limit=limit, offset=offset)

        items = self._run(_call()) or []
        return [
            MemoryRecord(
                namespace=_ns_key(getattr(i, "namespace", namespace)),
                key=str(getattr(i, "key", "")),
                value=dict(getattr(i, "value", {}) or {}),
                created_at=str(getattr(i, "created_at", "") or ""),
                updated_at=str(getattr(i, "updated_at", "") or ""),
            )
            for i in items
        ]

    def namespaces(self, prefix=()):
        return []  # BaseStore 不保证提供枚举能力，按用途自行维护
