"""Orchestrator 集成测试：验证「质检→路由→索引→(可能)编译」的完整调度。

这条链路是本轮升级的核心：验证 hot 分层文档真的进了 Wiki，
cold 分层文档（质检不过/扫描件/长尾）真的没进 Wiki 但仍可被 RAG 检索到。
"""
from __future__ import annotations

from pke.agents.orchestrator import Orchestrator
from pke.schemas import Document


def test_clean_document_is_indexed_and_compiled(tmp_path):
    orch = Orchestrator(tmp_path / "wiki")
    doc = Document(source="a.md", source_type="text", title="多Agent编排")
    doc.add_chunk("Orchestrator 负责调度质检、路由、索引和编译四个专项 Agent。")

    report = orch.ingest_document(doc)

    assert report.quality_passed is True
    assert report.route is not None
    assert report.route.tier == "hot"
    assert report.indexed_chunks == 1
    assert report.compiled_path is not None
    # 真的写进了 Wiki 磁盘文件，不是只在内存里
    assert (tmp_path / "wiki" / report.compiled_path).exists()


def test_scanned_document_is_indexed_but_not_compiled(tmp_path):
    orch = Orchestrator(tmp_path / "wiki")
    doc = Document(
        source="b.pdf",
        source_type="pdf",
        title="扫描件文档",
        meta={"needs_ocr_pages": [1, 2]},
    )
    doc.add_chunk("部分可识别的正文")

    report = orch.ingest_document(doc)

    assert report.route is not None
    assert report.route.tier == "cold"
    assert report.compiled_path is None  # 没有被编译进 Wiki
    assert report.indexed_chunks == 1  # 但仍然被索引，可被 RAG 检索

    # 用 Orchestrator.ask 验证：Wiki 查不到，RAG 能查到（Wiki优先/RAG兜底）
    answer = orch.ask("正文")
    assert answer.source == "rag"


def test_empty_document_fails_quality_and_stays_cold(tmp_path):
    orch = Orchestrator(tmp_path / "wiki")
    doc = Document(source="c.md", source_type="text", title="空文档")

    report = orch.ingest_document(doc)

    assert report.quality_passed is False
    assert report.route is not None
    assert report.route.tier == "cold"
    assert report.compiled_path is None
    assert report.indexed_chunks == 0  # 空文档没有 chunk 可索引


def test_orchestrator_ask_end_to_end(tmp_path):
    orch = Orchestrator(tmp_path / "wiki")
    doc = Document(source="a.md", source_type="text", title="知识路由")
    doc.add_chunk("知识路由决定查询该先看 Wiki 还是 RAG。")
    orch.ingest_document(doc)

    answer = orch.ask("知识路由")
    assert answer.source == "wiki"
    assert answer.wiki_pages
