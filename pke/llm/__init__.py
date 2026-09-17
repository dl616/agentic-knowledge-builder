"""LLM（大语言模型）接入层。

对外只暴露三个名字：LLMClient（客户端）、LLMResponse（响应）、LLMError（异常）。
业务代码只依赖这一层，换提供方（knot / deepseek / openai / ollama）不用改。
"""
from .client import ChatMessage, LLMClient, LLMError, LLMResponse

__all__ = ["ChatMessage", "LLMClient", "LLMError", "LLMResponse"]
