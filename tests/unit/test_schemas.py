"""schemas.py 的单元测试：验证数据契约的正确性。"""
from __future__ import annotations

import pytest

from pke.schemas import Chunk, Document


def test_chunk_normalizes_outer_whitespace_but_keeps_inner_newlines():
    c = Chunk(text="\n  def f():\n    return 1\n  \n")
    # 两侧空白去掉，内部换行缩进保留
    assert c.text == "def f():\n    return 1"


def test_document_add_chunk_injects_provenance():
    doc = Document(source="a.pdf", source_type="pdf", title="A")
    chunk = doc.add_chunk("正文", page=3, block_type="text")
    assert chunk.metadata["source"] == "a.pdf"
    assert chunk.metadata["source_type"] == "pdf"
    assert chunk.metadata["page"] == 3
    assert chunk.metadata["block_type"] == "text"
    assert chunk.metadata["title"] == "A"


def test_document_rejects_unknown_source_type():
    with pytest.raises(ValueError):
        Document(source="x", source_type="not-a-type")


def test_document_total_size_sums_chunks():
    doc = Document(source="a", source_type="text")
    doc.add_chunk("12345")
    doc.add_chunk("abc")
    assert doc.total_size == 8
