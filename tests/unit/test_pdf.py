"""PDF 摄取器的单元测试：验证代码块保真（最关键的坑）。"""
from __future__ import annotations

from pke.agents.ingest.pdf import ingest_pdf


def test_pdf_preserves_code_indentation(sample_pdf_path):
    doc = ingest_pdf(sample_pdf_path, extract_images=False)

    code_chunks = [c for c in doc.chunks if c.metadata.get("block_type") == "code"]
    assert code_chunks, "应识别出代码块"

    code = code_chunks[0].text
    # 代码块必须保留原始换行和缩进（4 空格缩进），一个字符都不能差
    assert "def fib(n):" in code
    assert "    if n <= 1:" in code
    assert "    return fib(n - 1) + fib(n - 2)" in code


def test_pdf_extracts_text_blocks(sample_pdf_path):
    doc = ingest_pdf(sample_pdf_path, extract_images=False)
    text_chunks = [c for c in doc.chunks if c.metadata.get("block_type") == "text"]
    assert any("软换行" in c.text for c in text_chunks)


def test_pdf_document_carries_page_metadata(sample_pdf_path):
    doc = ingest_pdf(sample_pdf_path, extract_images=False)
    for c in doc.chunks:
        assert "page" in c.metadata
        assert c.metadata["page"] == 1
