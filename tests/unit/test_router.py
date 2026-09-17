"""Router 的单元测试：验证冷热分层判断和查询路由——诊断报告点名的缺口。"""
from __future__ import annotations

from pke.knowledge.compile import WikiStore
from pke.knowledge.rag import RagKnowledgeBase
from pke.knowledge.router import classify_tier, query_route
from pke.schemas import Document


def _clean_doc(n_chunks: int = 3) -> Document:
    doc = Document(source="a.md", source_type="text", title="干净文档")
    for i in range(n_chunks):
        doc.add_chunk(f"第 {i} 段正常内容。")
    return doc


def test_clean_small_document_is_hot():
    decision = classify_tier(_clean_doc())
    assert decision.tier == "hot"
    assert "编译进 Wiki" in decision.reason


def test_quality_failed_document_is_cold_regardless_of_size():
    decision = classify_tier(_clean_doc(), quality_passed=False)
    assert decision.tier == "cold"
    assert "质检未通过" in decision.reason


def test_scanned_document_is_cold():
    doc = Document(
        source="a.pdf",
        source_type="pdf",
        title="扫描件",
        meta={"needs_ocr_pages": [1]},
    )
    doc.add_chunk("正文")

    decision = classify_tier(doc)
    assert decision.tier == "cold"
    assert "扫描件" in decision.reason


def test_large_document_is_cold_long_tail():
    doc = _clean_doc(n_chunks=50)  # 超过 COLD_TIER_MIN_CHUNKS=30
    decision = classify_tier(doc)
    assert decision.tier == "cold"
    assert "长尾" in decision.reason


def test_query_route_prefers_wiki_when_hit(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")
    kb = RagKnowledgeBase()

    doc = Document(source="a.md", source_type="text", title="LangGraph编排")
    doc.add_chunk("LangGraph 是多 Agent 编排框架")
    wiki.ingest(doc)
    kb.add(doc)

    result = query_route(wiki, kb, "LangGraph")
    assert result.source == "wiki"
    assert result.wiki_pages


def test_query_route_falls_back_to_rag_when_wiki_misses(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")
    kb = RagKnowledgeBase()

    # 只进 RAG，不编译进 Wiki（模拟 cold 分层文档）
    doc = Document(source="b.md", source_type="text", title="其他标题")
    doc.add_chunk("BM25 检索是一种关键词检索算法")
    kb.add(doc)

    result = query_route(wiki, kb, "BM25 检索")
    assert result.source == "rag"
    assert result.rag_result is not None
    assert result.rag_result.results


def test_query_route_returns_none_when_nothing_hits(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")
    kb = RagKnowledgeBase()

    result = query_route(wiki, kb, "任何查询")
    assert result.source == "none"
