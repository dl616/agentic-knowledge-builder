"""Quality Agent 的单元测试：验证质检能检出真实问题，而不是永远通过。"""
from __future__ import annotations

from pke.agents.quality import inspect
from pke.schemas import Document


def test_healthy_document_passes():
    doc = Document(source="a.md", source_type="text", title="A")
    doc.add_chunk("这是一段正常的中文正文，内容清晰完整。")
    doc.add_chunk("def f():\n    return 1", block_type="code")

    report = inspect(doc)
    assert report.passed is True
    assert report.issues == []


def test_empty_document_fails():
    doc = Document(source="a.md", source_type="text", title="空文档")
    report = inspect(doc)
    assert report.passed is False
    assert "没有任何 chunk" in report.issues[0]


def test_garbled_chunks_are_flagged():
    doc = Document(source="a.pdf", source_type="pdf", title="乱码测试")
    # 大量特殊符号/控制字符模拟提取失败产生的乱码
    doc.add_chunk("\ufffd\ufffd\x00\x01烷菁鸀\ufffd\ufffd\x02\x03镶錭")
    doc.add_chunk("这是一段正常的正文内容。")

    report = inspect(doc)
    assert report.garbled_chunk_count >= 1
    assert any("乱码" in i for i in report.issues)


def test_scanned_pages_are_flagged_but_dont_always_fail():
    doc = Document(
        source="a.pdf",
        source_type="pdf",
        title="扫描件",
        meta={"needs_ocr_pages": [1, 2]},
    )
    doc.add_chunk("这是数字版部分的正文。")

    report = inspect(doc)
    assert any("扫描件页面" in i for i in report.issues)


def test_mostly_garbled_document_fails():
    doc = Document(source="a.pdf", source_type="pdf", title="严重乱码")
    for _ in range(5):
        doc.add_chunk("\ufffd\ufffd\x00\x01烷菁鸀\ufffd\ufffd\x02\x03镶錭乱码内容测试")
    doc.add_chunk("唯一一段正常内容。")

    report = inspect(doc)
    assert report.passed is False
