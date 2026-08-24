"""Compile 层（LLM-Wiki 沉淀骨架）的单元测试。"""
from __future__ import annotations

from pke.knowledge.compile import WikiStore
from pke.schemas import Document


def test_wikistore_creates_structure(tmp_path):
    WikiStore(tmp_path / "wiki")
    assert (tmp_path / "wiki" / "index.md").exists()
    assert (tmp_path / "wiki" / "log.md").exists()
    assert (tmp_path / "wiki" / "schema.md").exists()
    assert (tmp_path / "wiki" / "concepts").exists()
    assert (tmp_path / "wiki" / "entities").exists()
    assert (tmp_path / "wiki" / "synthesis").exists()


def test_ingest_creates_page_updates_index_and_log(tmp_path):
    store = WikiStore(tmp_path / "wiki")
    doc = Document(source="a.pdf", source_type="pdf", title="多Agent编排")
    doc.add_chunk("def f():\n    return 1", block_type="code")

    rel = store.ingest(doc)

    assert (tmp_path / "wiki" / rel).exists()
    assert "多Agent编排" in (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "ingest" in (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")


def test_render_preserves_code_indentation(tmp_path):
    store = WikiStore(tmp_path / "wiki")
    doc = Document(source="a.md", source_type="text", title="代码")
    doc.add_chunk("def f():\n    return 1", block_type="code")

    rel = store.ingest(doc)
    content = (tmp_path / "wiki" / rel).read_text(encoding="utf-8")
    assert "    return 1" in content  # 代码缩进保留


def test_query_finds_page_by_title(tmp_path):
    store = WikiStore(tmp_path / "wiki")
    doc = Document(source="a.pdf", source_type="pdf", title="LangGraph编排")
    store.ingest(doc)

    results = store.query("LangGraph")
    assert len(results) == 1
    assert results[0].title == "LangGraph编排"


def test_lint_detects_orphan_page(tmp_path):
    store = WikiStore(tmp_path / "wiki")
    (tmp_path / "wiki" / "concepts" / "orphan.md").write_text("# orphan\n", encoding="utf-8")

    issues = store.lint()
    assert any("孤儿" in i for i in issues)
