"""Agent 层：多 Agent 知识构建平台的核心。

- base.py：Agent 抽象基类 + AgentMessage 契约。
- ingest/：摄取 Agent（PDF/文本/网页）。
- index.py / retrieval.py / answer.py / compile.py：索引 / 检索 / 问答 / 沉淀 Agent。
- 后续：quality.py / orchestrator.py。
"""
from .answer import AnswerAgent
from .base import Agent, AgentMessage
from .compile import CompileAgent
from .index import IndexAgent
from .retrieval import RetrievalAgent

__all__ = [
    "Agent",
    "AgentMessage",
    "IndexAgent",
    "RetrievalAgent",
    "AnswerAgent",
    "CompileAgent",
]
