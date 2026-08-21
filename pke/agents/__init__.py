"""Agent 层：多 Agent 知识构建平台的核心。

- base.py：Agent 抽象基类 + AgentMessage 契约。
- ingest/：摄取 Agent（PDF/文本，后续加网页/图片）。
- 后续：quality.py / index.py / retrieval.py / answer.py / orchestrator.py。
"""
from .base import Agent, AgentMessage

__all__ = ["Agent", "AgentMessage"]
