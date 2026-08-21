"""索引 Agent：把摄取出的 Document 写入可检索的知识库。

输入：AgentMessage(payload=Document)
输出：AgentMessage(payload=Document, meta 含 chunk_count / total_chunks)

阶段 B 是薄封装，核心逻辑在 knowledge.RagKnowledgeBase。
"""
from __future__ import annotations

from ..knowledge import RagKnowledgeBase
from ..schemas import Document
from .base import Agent, AgentMessage


class IndexAgent(Agent):
    name = "index"

    def __init__(self, kb: RagKnowledgeBase) -> None:
        self._kb = kb

    def run(self, msg: AgentMessage) -> AgentMessage:
        document = msg.payload
        if not isinstance(document, Document):
            raise TypeError(f"IndexAgent 期望 Document，收到 {type(document)!r}")

        added = self._kb.add(document)
        return AgentMessage(
            payload=document,
            meta={"chunk_count": added, "total_chunks": self._kb.chunk_count},
        )
