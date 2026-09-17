"""LLM（大语言模型）客户端单元测试。

全部用打桩（stub）替代真实 HTTP，不联网、不依赖密钥，
保证「没配 LLM 也能跑 CI」——这是本项目的一贯要求。
"""
from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from pke.llm import ChatMessage, LLMClient, LLMError, LLMResponse


class _FakeResponse:
    """假的 HTTP 响应：只需要支持 read() 与上下文管理协议。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> bool:
        return False


def _openai_payload(content: str = "你好", model: str = "test-model") -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            },
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _make_client(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> tuple[LLMClient, list]:
    """构造一个 urlopen 被打桩的客户端，并返回捕获到的请求列表。"""
    captured: list[Any] = []

    def fake_urlopen(request: Any, timeout: float | None = None, **_: Any) -> _FakeResponse:
        captured.append(request)
        return _FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = LLMClient(
        base_url="https://llm.example.com/v1",
        api_key="test-key",
        model="test-model",
        timeout=5,
        temperature=0.1,
        max_retries=0,
    )
    return client, captured


# ---- 配置与地址 ----


def test_is_configured_requires_base_url_and_key() -> None:
    assert LLMClient(base_url="https://x/v1", api_key="k").is_configured() is True
    assert LLMClient(base_url="", api_key="k").is_configured() is False
    assert LLMClient(base_url="https://x/v1", api_key="").is_configured() is False


def test_endpoint_strips_trailing_slash() -> None:
    client = LLMClient(base_url="https://llm.example.com/v1/", api_key="k")
    assert client.endpoint() == "https://llm.example.com/v1/chat/completions"


def test_chat_without_config_raises_llm_error() -> None:
    client = LLMClient(base_url="", api_key="")
    with pytest.raises(LLMError, match="未配置"):
        client.complete("hi")


# ---- 正常解析 ----


def test_chat_parses_openai_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client, captured = _make_client(monkeypatch, _openai_payload("生成成功"))

    result = client.chat([ChatMessage(role="user", content="帮我生成用例")])

    assert isinstance(result, LLMResponse)
    assert result.content == "生成成功"
    assert result.model == "test-model"
    assert result.finish_reason == "stop"
    assert result.usage["total_tokens"] == 15

    request = captured[0]
    assert request.full_url == "https://llm.example.com/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-key"


def test_chat_accepts_dict_messages_and_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client, captured = _make_client(monkeypatch, _openai_payload())

    client.chat([{"role": "system", "content": "你是测试专家"}, {"role": "user", "content": "hi"}])

    body = json.loads(captured[0].data.decode("utf-8"))
    assert body["model"] == "test-model"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["temperature"] == pytest.approx(0.1)


def test_complete_includes_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    client, captured = _make_client(monkeypatch, _openai_payload("结果"))

    text = client.complete("生成登录用例", system="你是测试专家")

    assert text == "结果"
    body = json.loads(captured[0].data.decode("utf-8"))
    assert body["messages"][0] == {"role": "system", "content": "你是测试专家"}


def test_json_mode_adds_response_format(monkeypatch: pytest.MonkeyPatch) -> None:
    client, captured = _make_client(monkeypatch, _openai_payload('{"cases": []}'))

    client.complete("生成用例", json_mode=True, max_tokens=512)

    body = json.loads(captured[0].data.decode("utf-8"))
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 512


def test_extra_headers_are_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    client, captured = _make_client(monkeypatch, _openai_payload())
    client.extra_headers = {"X-Source": "akb"}

    client.complete("hi")

    assert captured[0].get_header("X-source") == "akb"


# ---- 错误处理 ----


def _raise_http_error(code: int, body: str = '{"error":"bad"}') -> Any:
    def fake_urlopen(request: Any, timeout: float | None = None, **_: Any) -> _FakeResponse:
        raise urllib.error.HTTPError(
            "https://llm.example.com/v1/chat/completions",
            code,
            "error",
            {},
            io.BytesIO(body.encode("utf-8")),
        )

    return fake_urlopen


def test_4xx_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_urlopen(request: Any, timeout: float | None = None, **_: Any) -> _FakeResponse:
        calls["n"] += 1
        body = io.BytesIO(b'{"error":"bad key"}')
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("pke.llm.client.time.sleep", lambda *_: None)
    client = LLMClient(base_url="https://llm.example.com/v1", api_key="k", max_retries=3)

    with pytest.raises(LLMError, match="401"):
        client.complete("hi")
    assert calls["n"] == 1, "401 是参数/鉴权错误，重试无意义，应只调用一次"


def test_5xx_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"n": 0}

    def fake_urlopen(request: Any, timeout: float | None = None, **_: Any) -> _FakeResponse:
        state["n"] += 1
        if state["n"] == 1:
            raise urllib.error.HTTPError("u", 503, "busy", {}, io.BytesIO(b"upstream down"))
        return _FakeResponse(_openai_payload("恢复成功"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("pke.llm.client.time.sleep", lambda *_: None)
    client = LLMClient(base_url="https://llm.example.com/v1", api_key="k", max_retries=2)

    assert client.complete("hi") == "恢复成功"
    assert state["n"] == 2


def test_5xx_exhausted_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _raise_http_error(500))
    monkeypatch.setattr("pke.llm.client.time.sleep", lambda *_: None)
    client = LLMClient(base_url="https://llm.example.com/v1", api_key="k", max_retries=1)

    with pytest.raises(LLMError, match="500"):
        client.complete("hi")


def test_network_error_raises_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float | None = None, **_: Any) -> _FakeResponse:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("pke.llm.client.time.sleep", lambda *_: None)
    client = LLMClient(base_url="https://llm.example.com/v1", api_key="k", max_retries=0)

    with pytest.raises(LLMError, match="网络"):
        client.complete("hi")


def test_malformed_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _make_client(monkeypatch, {"unexpected": "shape"})

    with pytest.raises(LLMError, match="响应结构异常"):
        client.complete("hi")


def test_non_json_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _HtmlResponse(_FakeResponse):
        def read(self) -> bytes:
            return b"<!DOCTYPE html><html>login</html>"

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout=None, **_: _HtmlResponse({})
    )
    client = LLMClient(base_url="https://llm.example.com/v1", api_key="k", max_retries=0)

    with pytest.raises(LLMError, match="不是合法 JSON"):
        client.complete("hi")


def test_empty_usage_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _openai_payload()
    payload.pop("usage")
    client, _ = _make_client(monkeypatch, payload)

    assert client.complete("hi") == "你好"
