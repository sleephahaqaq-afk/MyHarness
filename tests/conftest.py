"""pytest 公共夹具：把 src 加入 sys.path，并为测试注入必需环境变量。

基座要求 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 必须存在（零回退），
测试里显式提供假值——这不是产品默认值，只是让装配链路可跑。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:1/v1")
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "scripted-model")
