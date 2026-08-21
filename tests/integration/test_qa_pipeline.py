"""问答闭环（index → retrieval → answer 三 Agent 串起来）的集成测试。"""
from __future__ import annotations

import pytest

from pke.agents import AnswerAgent, IndexAgent, RetrievalAgent
from pke.agents.base import AgentMessage
from pke.knowledge import RagKnowledgeBase
from pke.schemas import Document


def _make_doc() -> Document:
    doc = Document(source="notes.md", source_type="text", title="技术笔记")
    doc.add_chunk("多 Agent 系统通过 LangGraph 进行编排")
    doc.add_chunk("知识库使用 BM25 关键词检索和向量检索混合")
    doc.add_chunk("摄取层负责把 PDF 网页代码解析成结构化文档")
    return doc


def test_qa_pipeline_end_to_end():
    kb = RagKnowledgeBase()
    index = IndexAgent(kb)
    retrieval = RetrievalAgent(kb)
    answer = AnswerAgent(kb)

    # 1. 索引
    index_result = index.run(AgentMessage(payload=_make_doc()))
    assert index_result.meta["total_chunks"] == 3

    # 2. 检索
    retrieval_result = retrieval.run(AgentMessage(payload="知识库怎么检索"))
    assert retrieval_result.meta["hit_count"] >= 1
    assert any("BM25" in r.chunk.text for r in retrieval_result.payload)

    # 3. 问答（带引用）
    answer_result = answer.run(AgentMessage(payload="知识库怎么检索"))
    assert answer_result.meta["citation_count"] >= 1
    assert "[1]" in answer_result.payload.context


def test_index_agent_rejects_non_document():
    kb = RagKnowledgeBase()
    index = IndexAgent(kb)
    with pytest.raises(TypeError):
        index.run(AgentMessage(payload="不是文档"))
