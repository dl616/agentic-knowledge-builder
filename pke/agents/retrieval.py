"""检索 Agent：根据查询召回最相关的 chunk。

输入：AgentMessage(payload=查询字符串, meta.top_k 可选)
输出：AgentMessage(payload=list[SearchResult], meta 含 query / hit_count)
"""
from __future__ import annotations

from ..knowledge import RagKnowledgeBase
from .base import Agent, AgentMessage


class RetrievalAgent(Agent):
    name = "retrieval"

    def __init__(self, kb: RagKnowledgeBase) -> None:
        self._kb = kb

    def run(self, msg: AgentMessage) -> AgentMessage:
        query = msg.payload
        if not isinstance(query, str):
            raise TypeError(f"RetrievalAgent 期望 str 查询，收到 {type(query)!r}")

        top_k = msg.meta.get("top_k", 5)
        results = self._kb.search(query, top_k=top_k)
        return AgentMessage(
            payload=results,
            meta={"query": query, "hit_count": len(results)},
        )
