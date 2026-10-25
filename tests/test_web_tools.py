"""联网工具测试：SSRF 防护、HTML 清洗、截断、搜索配置与返回解析。"""
from __future__ import annotations

import pytest

from harness.tools.web import (
    ensure_public_url,
    extract_response_text,
    strip_html,
    web_fetch,
    web_search,
)


class _Response:
    def __init__(self, *, status_code=200, text="", content=None, content_type="text/html"):
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = {"content-type": content_type}

    def json(self):
        return self._json

    def _set_json(self, value):
        self._json = value


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/x",
        "http://10.0.0.1/x",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "",
    ],
)
def test_ssrf_guard_blocks_non_public_targets(url):
    with pytest.raises(ValueError):
        ensure_public_url(url)


def test_strip_html_drops_script_and_style():
    html = "<html><head><style>.a{color:red}</style></head><body><h1>AI 周报</h1><script>steal()</script></body></html>"
    text = strip_html(html)
    assert "AI 周报" in text
    assert "steal()" not in text and "color:red" not in text


def test_web_fetch_refuses_private_host():
    result = web_fetch.invoke({"url": "http://127.0.0.1:8000/admin"})
    assert result.startswith("拒绝访问")


def test_web_fetch_converts_html_and_truncates(monkeypatch):
    long_text = "<html><body>" + ("<p>模型发布</p>" * 2000) + "</body></html>"
    monkeypatch.setattr("harness.tools.web.ensure_public_url", lambda url: url)
    monkeypatch.setattr(
        "harness.tools.web.httpx.get", lambda *a, **k: _Response(text=long_text)
    )

    result = web_fetch.invoke({"url": "https://example.com/news", "max_chars": 1000})
    assert "模型发布" in result
    assert "内容已截断" in result
    assert len(result) < 1200


def test_web_fetch_rejects_unsupported_content_type(monkeypatch):
    monkeypatch.setattr("harness.tools.web.ensure_public_url", lambda url: url)
    monkeypatch.setattr(
        "harness.tools.web.httpx.get",
        lambda *a, **k: _Response(text="binary", content_type="application/pdf"),
    )
    assert web_fetch.invoke({"url": "https://example.com/a.pdf"}).startswith("不支持的内容类型")


def test_web_search_reports_missing_config(monkeypatch):
    monkeypatch.delenv("WEB_SEARCH_MODEL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")

    result = web_search.invoke({"query": "AI 新闻"})
    assert result.startswith("搜索失败")
    assert "WEB_SEARCH_MODEL" in result


def test_search_config_missing_matches_health_and_tool(monkeypatch):
    """`/api/health` 和 web_search 必须用同一份判断。

    曾经的现象：health 报 `missing_config: []` 一切正常，但模型说"我无法联网检索"——
    因为 WEB_SEARCH_MODEL 没配，工具在发请求前就禁用了自己。
    """
    from harness.tools.web import search_config_missing

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.delenv("WEB_SEARCH_URL", raising=False)
    monkeypatch.delenv("WEB_SEARCH_MODEL", raising=False)
    missing = search_config_missing()
    assert missing == ["WEB_SEARCH_MODEL"]
    assert "WEB_SEARCH_MODEL" in web_search.invoke({"query": "AI 新闻"})

    monkeypatch.setenv("WEB_SEARCH_MODEL", "deepseek-chat")
    assert search_config_missing() == []


def test_web_search_sends_time_hint_and_returns_summary(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        response = _Response(text="")
        response._set_json({"output_text": "本周发布了模型 A（官方博客，2026-10-23）"})
        return response

    monkeypatch.setenv("WEB_SEARCH_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.delenv("WEB_SEARCH_URL", raising=False)
    monkeypatch.setattr("harness.tools.web.httpx.post", fake_post)

    result = web_search.invoke({"query": "AI 模型发布", "time_range": "week"})
    assert "模型 A" in result
    assert captured["url"] == "https://api.example.com/v1/responses"
    assert "最近 7 天" in captured["payload"]["input"]
    assert captured["payload"]["tools"] == [{"type": "web_search"}]


def test_web_search_surfaces_http_error(monkeypatch):
    def fake_post(*args, **kwargs):
        response = _Response(status_code=429, text="rate limited")
        response._set_json({"error": {"message": "rate limited"}})
        return response

    monkeypatch.setenv("WEB_SEARCH_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setattr("harness.tools.web.httpx.post", fake_post)

    result = web_search.invoke({"query": "x"})
    assert result.startswith("搜索失败") and "rate limited" in result


def test_extract_response_text_handles_both_shapes():
    assert extract_response_text({"output_text": " summary "}) == "summary"
    nested = {
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "a"}]},
            {"type": "message", "content": [{"type": "text", "text": "b"}]},
            {"type": "tool_call", "content": []},
        ]
    }
    assert extract_response_text(nested) == "a\nb"
    assert extract_response_text({}) == ""


def test_web_fetch_retries_transient_transport_error(monkeypatch):
    """代理抖动造成瞬时 502/连接重置时重试一次，不该直接放弃整个来源。"""
    import httpx as real_httpx

    calls = {"n": 0}

    def flaky_get(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise real_httpx.ProxyError("502 Bad Gateway")
        return _Response(text="<html><body>ok AI news</body></html>")

    monkeypatch.setattr("harness.tools.web.httpx.get", flaky_get)
    result = web_fetch.invoke({"url": "https://example.com/news"})
    assert "ok AI news" in result
    assert calls["n"] == 2


def test_web_fetch_gives_up_after_second_transport_error(monkeypatch):
    import httpx as real_httpx

    calls = {"n": 0}

    def dead_get(*args, **kwargs):
        calls["n"] += 1
        raise real_httpx.ConnectError("connection refused")

    monkeypatch.setattr("harness.tools.web.httpx.get", dead_get)
    result = web_fetch.invoke({"url": "https://example.com/news"})
    assert result.startswith("请求异常")
    assert "已重试一次" in result
    assert calls["n"] == 2
