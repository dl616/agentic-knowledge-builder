"""Agent 层：多 Agent 知识构建平台的核心。

- base.py：Agent 抽象基类 + AgentMessage 契约。
- ingest/：摄取 Agent（PDF/文本/网页）。
- index.py / retrieval.py / answer.py / compile.py / quality.py：五个专项 Agent。
- orchestrator.py：总控 Agent，调度「质检→路由→索引→(可能)编译」和「Wiki优先/RAG兜底」查询。
"""
from .answer import AnswerAgent
from .base import Agent, AgentMessage
from .compile import CompileAgent
from .index import IndexAgent
from .orchestrator import IngestReport, Orchestrator
from .quality import QualityAgent, QualityReport
from .retrieval import RetrievalAgent

__all__ = [
    "Agent",
    "AgentMessage",
    "IndexAgent",
    "RetrievalAgent",
    "AnswerAgent",
    "CompileAgent",
    "QualityAgent",
    "QualityReport",
    "Orchestrator",
    "IngestReport",
]
