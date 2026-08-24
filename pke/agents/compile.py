"""Compile Agent：把摄取结果沉淀进 LLM-Wiki。

输入：AgentMessage(payload=Document)
输出：AgentMessage(payload=相对路径, meta 含 title / chunk_count)

阶段 C 是「归档式编译」（不依赖 LLM），核心在 knowledge.WikiStore。
LLM 智能编译后续接入。
"""
from __future__ import annotations

from ..knowledge import WikiStore
from ..schemas import Document
from .base import Agent, AgentMessage


class CompileAgent(Agent):
    name = "compile"

    def __init__(self, wiki: WikiStore) -> None:
        self._wiki = wiki

    def run(self, msg: AgentMessage) -> AgentMessage:
        document = msg.payload
        if not isinstance(document, Document):
            raise TypeError(f"CompileAgent 期望 Document，收到 {type(document)!r}")

        rel_path = self._wiki.ingest(document)
        return AgentMessage(
            payload=rel_path,
            meta={"title": document.title, "chunk_count": len(document.chunks)},
        )
