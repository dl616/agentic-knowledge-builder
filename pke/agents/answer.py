"""问答 Agent：把检索到的片段组装成带编号引用的回答。

输入：AgentMessage(payload=查询字符串, meta.top_k 可选)
输出：AgentMessage(payload=AnswerResult, meta 含 query / citation_count)

阶段 B 是「检索式回答」——返回相关片段 + 出处，不调 LLM。
LLM 生成通过可插拔 adapter 在后续接入（接口见 meta 说明）。
"""
from __future__ import annotations

from ..knowledge import RagKnowledgeBase
from .base import Agent, AgentMessage


class AnswerAgent(Agent):
    name = "answer"

    def __init__(self, kb: RagKnowledgeBase) -> None:
        self._kb = kb

    def run(self, msg: AgentMessage) -> AgentMessage:
        query = msg.payload
        if not isinstance(query, str):
            raise TypeError(f"AnswerAgent 期望 str 查询，收到 {type(query)!r}")

        top_k = msg.meta.get("top_k", 5)
        result = self._kb.answer(query, top_k=top_k)
        return AgentMessage(
            payload=result,
            meta={"query": query, "citation_count": len(result.citations)},
        )
