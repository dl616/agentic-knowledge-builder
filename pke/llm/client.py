"""LLM（大语言模型）客户端 —— OpenAI 兼容协议，零第三方依赖。

三个设计决策：

1. **零依赖**：用标准库 urllib 实现，不引入 openai / httpx SDK。
   项目已有的依赖都是「必要且轻量」的，为一个 HTTP 调用拖进整条 SDK 依赖链不划算，
   而且自研后请求/重试/错误处理完全可控、可打桩测试。

2. **协议统一**：只认 OpenAI 的 ``POST {base_url}/chat/completions`` 契约。
   于是 knot（腾讯内部平台）/ deepseek / openai / 本地 ollama 之间切换，
   只是换 ``base_url`` + ``model`` 两行配置，业务代码一行不动。

3. **显式降级**：``is_configured()`` 让调用方先判断有没有配好，
   没配好就走规则兜底（例如用例生成退回模板），而不是运行时崩掉。
   这是本项目「LLM 可插拔增强、绝不阻塞主流程」原则的落地。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .. import config

# 可重试的 HTTP 状态码：限流与服务端错误，重试有意义；4xx 参数错误重试无意义
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """LLM（大语言模型）调用失败。

    调用方只需捕获这一个异常，不必区分是网络问题、鉴权问题还是返回体畸形。
    """


@dataclass
class ChatMessage:
    """一条对话消息。"""

    role: str  # system（系统指令）/ user（用户）/ assistant（助手）
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    """LLM 响应。

    content      : 模型输出的文本（最常用）。
    model        : 实际使用的模型名（服务端可能回传与请求不同的值）。
    finish_reason: 结束原因，stop（正常结束）/ length（被截断）等。
    usage        : token（词元）用量，用于成本核算。
    raw          : 原始响应体，排查问题时用。
    """

    content: str
    model: str = ""
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def _as_messages(
    messages: Sequence[ChatMessage | Mapping[str, str]],
) -> list[dict[str, str]]:
    """把 ChatMessage 或 dict 统一转成协议要求的 dict 列表。"""
    result: list[dict[str, str]] = []
    for m in messages:
        if isinstance(m, ChatMessage):
            result.append(m.to_dict())
        else:
            result.append(
                {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
            )
    return result


class LLMClient:
    """OpenAI 兼容协议的 LLM 客户端。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        *,
        timeout: float | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else config.LLM_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else config.LLM_API_KEY
        self.model = model if model is not None else config.LLM_MODEL
        self.timeout = float(timeout if timeout is not None else config.LLM_TIMEOUT)
        self.temperature = float(temperature if temperature is not None else config.LLM_TEMPERATURE)
        self.max_retries = int(max_retries if max_retries is not None else config.LLM_MAX_RETRIES)
        self.extra_headers = dict(extra_headers or {})

    @classmethod
    def from_config(cls, **kwargs: Any) -> LLMClient:
        """按全局配置构造客户端（默认入口）。"""
        return cls(**kwargs)

    # ---- 状态判断 ----

    def is_configured(self) -> bool:
        """是否已具备调用条件（缺 base_url 或密钥都应走规则兜底）。"""
        return bool(self.base_url and self.api_key)

    def endpoint(self) -> str:
        """完整的 chat/completions 地址，排查与自检时打印用。"""
        return f"{self.base_url}/chat/completions"

    # ---- 核心调用 ----

    def chat(
        self,
        messages: Sequence[ChatMessage | Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        extra_body: Mapping[str, Any] | None = None,
    ) -> LLMResponse:
        """发起一次对话补全。

        json_mode: 要求模型返回合法 JSON（结构化输出场景，如生成测试用例）。
        """
        if not self.is_configured():
            raise LLMError(
                "LLM 未配置：缺少 base_url 或 api_key。"
                "请在项目根目录 .env 中设置 LLM_BASE_URL / LLM_API_KEY，或改用规则兜底。"
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _as_messages(messages),
            "temperature": self.temperature if temperature is None else temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if extra_body:
            payload.update(extra_body)

        raw = self._post(payload)
        return self._parse(raw)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        **kwargs: Any,
    ) -> str:
        """便捷方法：只想要文本时用它，省去手工拼 messages。"""
        messages: list[ChatMessage] = []
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.append(ChatMessage(role="user", content=prompt))
        return self.chat(messages, **kwargs).content

    # ---- 内部实现 ----

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 HTTP 请求，带重试与统一错误包装。"""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: str = ""

        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(self.endpoint(), data=data, method="POST")
            request.add_header("Content-Type", "application/json")
            request.add_header("Authorization", f"Bearer {self.api_key}")
            for key, value in self.extra_headers.items():
                request.add_header(key, value)

            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8", "ignore")
                return json.loads(body)  # type: ignore[no-any-return]

            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "ignore")[:500]
                last_error = f"HTTP {exc.code}: {detail}"
                if exc.code not in _RETRYABLE_STATUS or attempt == self.max_retries:
                    raise LLMError(f"LLM 请求失败（{self.endpoint()}）{last_error}") from exc

            except urllib.error.URLError as exc:
                last_error = f"网络错误 {exc.reason}"
                if attempt == self.max_retries:
                    raise LLMError(f"LLM 网络不可达（{self.endpoint()}）{last_error}") from exc

            except json.JSONDecodeError as exc:
                raise LLMError(f"LLM 返回体不是合法 JSON：{exc}") from exc

            # 指数退避：1s、2s、4s……避免限流时把服务端打得更惨
            time.sleep(2**attempt)

        raise LLMError(f"LLM 重试 {self.max_retries} 次后仍失败：{last_error}")

    @staticmethod
    def _parse(raw: dict[str, Any]) -> LLMResponse:
        """从 OpenAI 协议的响应体里取出需要的字段。"""
        try:
            choice = raw["choices"][0]
            content = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM 响应结构异常，取不到 choices[0].message.content：{raw}") from exc

        usage_raw = raw.get("usage") or {}
        usage = {
            key: int(usage_raw[key])
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(usage_raw.get(key), (int, float))
        }
        return LLMResponse(
            content=content,
            model=str(raw.get("model", "")),
            finish_reason=str(choice.get("finish_reason", "")),
            usage=usage,
            raw=raw,
        )
