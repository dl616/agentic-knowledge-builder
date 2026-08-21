"""文本/Markdown 摄取器的单元测试。"""
from __future__ import annotations

from pke.agents.ingest.text import ingest_text


def test_markdown_splits_heading_code_paragraph(tmp_path):
    p = tmp_path / "note.md"
    p.write_text(
        "# 标题一\n\n"
        "这是一段正文。\n\n"
        "```python\n"
        "def hello():\n"
        "    return 'world'\n"
        "```\n\n"
        "第二段正文。\n"
    )

    doc = ingest_text(p)

    types = [c.metadata.get("block_type") for c in doc.chunks]
    assert types == ["heading", "text", "code", "text"]

    code = [c for c in doc.chunks if c.metadata.get("block_type") == "code"][0]
    # 代码块保留缩进
    assert "    return 'world'" in code.text


def test_markdown_tracks_section(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("# 第一章\n\n内容\n")
    doc = ingest_text(p)
    body = [c for c in doc.chunks if c.metadata.get("block_type") == "text"][0]
    assert body.metadata["section"] == "第一章"


def test_plain_text_splits_by_blank_line(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("第一段\n\n第二段\n")
    doc = ingest_text(p)
    assert len([c for c in doc.chunks if c.metadata.get("block_type") == "text"]) == 2
