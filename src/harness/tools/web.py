"""联网工具：web_search + web_fetch。

设计取舍：
- **搜索**走 DeepSeek Responses API 的服务端内置 ``web_search`` 工具，不需要
  再申请 Tavily / Bing / Serper 第二个搜索 key；端点从 ``LLM_BASE_URL`` 推导
  （``<base>/responses``），可用 ``WEB_SEARCH_URL`` 覆盖。
- **抓取**自己做 HTML→文本，并加 **SSRF 防护**：只放行 http/https，解析出的所有
  IP 必须是公网地址（挡住 127.0.0.1 / 10.x / 192.168.x / 169.254.x / ::1 等）。
- 工具失败返回**可读错误字符串**而不是抛异常：抛异常会中断整张图，
  而模型看到错误还能换个查法。
"""
from __future__ import annotations

import ipaddress
import re
import socket
from typing import List, Optional
from urllib.parse import urlparse

import httpx
from langchain_core.tools import tool

from ..env_utils import env_int, optional_env
from ..log_utils import agent_logger

DEFAULT_TIMEOUT = 30.0
MAX_FETCH_BYTES = 2 * 1024 * 1024
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}

TIME_HINTS = {
    "day": "只关注最近 24 小时内的信息。",
    "week": "只关注最近 7 天内的信息。",
    "month": "只关注最近 30 天内的信息。",
    "any": "",
}

_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


# ---------------- 安全与清洗 ----------------

def ensure_public_url(url: str) -> str:
    """校验 URL 可安全抓取：协议合法、主机可解析、所有解析结果都是公网地址。"""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL 不能为空")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL 必须以 http:// 或 https:// 开头")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("URL 缺少主机名")
    if host in BLOCKED_HOSTNAMES or host.endswith(".local"):
        raise ValueError("拒绝访问本地主机")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError(f"无法解析主机: {host}") from exc

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not ip.is_global or ip.is_multicast or ip.is_loopback:
            raise ValueError(f"拒绝访问非公网地址: {address}")
    return url.strip()


def strip_html(html: str) -> str:
    """简易 HTML → 纯文本。"""
    text = _SCRIPT_STYLE.sub(" ", html)
    text = _TAGS.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    return text


# ---------------- 搜索 ----------------

def _search_endpoint() -> Optional[str]:
    explicit = optional_env("WEB_SEARCH_URL")
    if explicit:
        return explicit
    base = optional_env("LLM_BASE_URL")
    if not base:
        return None
    return base.rstrip("/") + "/responses"


def search_config_missing() -> List[str]:
    """返回联网搜索缺失的配置项；空列表表示可用。

    抽成函数是因为 `/api/health` 也要报同一批缺失项——两处各写一份逻辑迟早会漂移，
    表现为「健康检查说没问题，但模型说它不能联网」。
    """
    return [
        name
        for name, value in (
            ("LLM_BASE_URL（或 WEB_SEARCH_URL）", _search_endpoint()),
            ("LLM_API_KEY", optional_env("LLM_API_KEY")),
            ("WEB_SEARCH_MODEL", optional_env("WEB_SEARCH_MODEL")),
        )
        if not value
    ]


def extract_response_text(payload: dict) -> str:
    """兼容 Responses API 的 output_text 与原始 output 两种返回形态。"""
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: List[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content", [])
        if isinstance(content, str):
            chunks.append(content)
            continue
        for block in content or []:
            if isinstance(block, dict) and block.get("type") in {"output_text", "text"}:
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
    return "\n".join(chunks).strip()


@tool
def web_search(query: str, time_range: str = "week") -> str:
    """联网搜索最新信息（服务端搜索，返回中文摘要）。

    Args:
        query: 搜索问题，写清实体与时间，例如"2026 年 10 月 新发布的大模型"
        time_range: 时间窗，day / week / month / any

    Returns:
        搜索摘要文本；失败时返回以"搜索失败"/"搜索异常"开头的说明
    """
    endpoint = _search_endpoint()
    api_key = optional_env("LLM_API_KEY")
    model = optional_env("WEB_SEARCH_MODEL")

    missing = search_config_missing()
    if missing:
        return (
            f"搜索失败: 未配置 {'、'.join(missing)}；联网搜索已禁用。"
            "在 .env 里补上 WEB_SEARCH_MODEL（通常填与 LLM_MODEL 相同的模型）后重启服务。"
        )

    instruction = TIME_HINTS.get(str(time_range or "week").lower(), TIME_HINTS["week"])
    user_input = f"{query}\n\n{instruction}" if instruction else query

    try:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "instructions": (
                    "你是联网搜索助手。使用 web_search 获取最新、可靠的信息，用中文总结；"
                    "每条结论后面用括号标注来源与发布日期；"
                    "信息不足、互相矛盾或无法确认时明确说明，不要补全没搜到的内容。"
                ),
                "input": user_input,
                "tools": [{"type": "web_search"}],
                "tool_choice": {"type": "web_search"},
                "temperature": 0.3,
                "max_output_tokens": env_int("WEB_SEARCH_MAX_TOKENS", 2000),
            },
            timeout=DEFAULT_TIMEOUT,
        )
    except httpx.TimeoutException:
        return "搜索超时，请缩短查询范围或稍后重试"
    except Exception as exc:
        agent_logger.error(f"web_search error: {type(exc).__name__}: {exc}")
        return f"搜索异常: {type(exc).__name__}"

    if response.status_code != 200:
        try:
            message = response.json().get("error", {}).get("message", str(response.status_code))
        except Exception:
            message = response.text[:200] or str(response.status_code)
        return f"搜索失败: {message}"

    try:
        text = extract_response_text(response.json())
    except Exception:
        return "搜索失败: 返回内容无法解析"
    if not text:
        return "搜索完成，但没有可读摘要（可能没有匹配结果）"

    agent_logger.info(f"web_search ok: {query[:50]}")
    return text


# ---------------- 抓取 ----------------

@tool
def web_fetch(url: str, max_chars: int = 8000) -> str:
    """抓取指定网页并转成纯文本（用于核对搜索结果的原始出处）。

    Args:
        url: 完整 http/https 地址
        max_chars: 返回的最大字符数

    Returns:
        网页正文；失败时返回"拒绝/请求失败/超时"等说明
    """
    try:
        target = ensure_public_url(url)
    except ValueError as exc:
        return f"拒绝访问: {exc}"

    limit = max(500, min(int(max_chars or 8000), env_int("WEB_FETCH_MAX_CHARS", 20000)))

    # 本机走系统代理出国，代理抖动会造成瞬时 502/连接重置；这类传输错误重试一次即可，
    # 不值得让调用方（子 Agent）为此放弃整个来源。
    response = None
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            response = httpx.get(
                target,
                follow_redirects=True,
                timeout=20.0,
                headers={"User-Agent": "MyHarness/0.1 (+web_fetch)"},
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0 and isinstance(exc, httpx.TransportError):
                agent_logger.warning(f"web_fetch retry after transport error: {type(exc).__name__}")
                continue
            break

    if response is None:
        agent_logger.error(f"web_fetch error: {type(last_error).__name__}: {last_error}")
        if isinstance(last_error, httpx.TimeoutException):
            return f"请求超时: {target}"
        suffix = "（已重试一次，多半是代理抖动，可稍后再试）" if isinstance(last_error, httpx.TransportError) else ""
        return f"请求异常: {type(last_error).__name__}{suffix}"

    if response.status_code != 200:
        return f"请求失败: HTTP {response.status_code}"
    if len(response.content) > MAX_FETCH_BYTES:
        return f"拒绝处理: 内容超过 {MAX_FETCH_BYTES // 1024 // 1024} MB 上限"

    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        text = strip_html(response.text)
    elif content_type.startswith(("text/", "application/json", "application/xml")):
        text = response.text
    else:
        return f"不支持的内容类型: {content_type or 'unknown'}"

    if len(text) > limit:
        text = text[:limit] + f"\n... [内容已截断，原文共 {len(response.text)} 字符]"
    agent_logger.info(f"web_fetch ok: {target} ({len(text)} chars)")
    return text


def default_web_tools():
    """返回基座内置的联网工具列表。"""
    return [web_search, web_fetch]
