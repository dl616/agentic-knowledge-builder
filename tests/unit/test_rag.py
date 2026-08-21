"""RAG 层（BM25 索引 + 检索 + 带引用）的单元测试。"""
from __future__ import annotations

from pke.knowledge.rag import RagKnowledgeBase, tokenize
from pke.schemas import Document


def test_tokenize_splits_chinese_and_english():
    tokens = tokenize("Python 是一种编程语言")
    # jieba 会分出中英文 token；"编程语言" 可能作为一个词，用包含判断更稳健
    assert "Python" in tokens
    assert any("编程" in t for t in tokens)


def test_add_and_search_recalls_relevant_chunk():
    kb = RagKnowledgeBase()
    doc = Document(source="a.txt", source_type="text", title="A")
    doc.add_chunk("Python 是一种广泛使用的编程语言")
    doc.add_chunk("北京是中国的首都")
    kb.add(doc)

    results = kb.search("编程语言")
    assert results
    assert "Python" in results[0].chunk.text


def test_search_returns_nothing_for_empty_kb():
    kb = RagKnowledgeBase()
    assert kb.search("任何查询") == []


def test_answer_builds_numbered_context_with_citations():
    kb = RagKnowledgeBase()
    doc = Document(source="a.txt", source_type="text", title="A")
    doc.add_chunk("Python 是一种编程语言")
    kb.add(doc)

    result = kb.answer("Python 是什么")

    assert "[1]" in result.context
    assert "Python 是一种编程语言" in result.context
    assert result.citations[0]["index"] == 1
    assert result.citations[0]["source"] == "a.txt"
    assert result.citations[0]["block_type"] == "text"
