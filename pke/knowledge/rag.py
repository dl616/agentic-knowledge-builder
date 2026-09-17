"""RAG 层：关键词检索（BM25）+ 带引用组装。

这是「问答闭环」的核心。当前用 BM25 关键词检索（快、纯 Python、可测试），
向量检索（embedding + 向量库）作为后续增强，接口已预留。

设计说明：
- add 把 Document 的 chunks 建立 BM25 索引。
- search 按查询召回最相关的 chunks（带得分）。
- answer 把召回片段组装成带编号引用 [1][2] 的上下文。
  阶段 B 先做「检索式回答」——返回相关片段 + 出处，不调 LLM；
  LLM 生成通过可插拔 adapter 在后续接入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import jieba  # type: ignore[import-untyped]  # jieba 无类型标注
from rank_bm25 import BM25Plus  # type: ignore[import-untyped]  # rank-bm25 无类型标注

from ..schemas import Chunk, Document


def tokenize(text: str) -> list[str]:
    """分词：中文用 jieba，英文/数字自然切分。"""
    return [w.strip() for w in jieba.cut(text) if w.strip()]


@dataclass
class SearchResult:
    """一次检索的结果：命中的 chunk + 得分。"""
    chunk: Chunk
    score: float


@dataclass
class AnswerResult:
    """一次问答的结果：查询 + 组装好的带引用上下文 + 出处。"""
    query: str
    context: str
    citations: list[dict[str, Any]]
    results: list[SearchResult] = field(default_factory=list)


class RagKnowledgeBase:
    """RAG 知识库：索引 + 检索 + 带引用组装。"""

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._bm25: BM25Plus | None = None

    def add(self, document: Document) -> int:
        """把一份 Document 的 chunks 加入索引，返回新增 chunk 数。

        真实边界坑：BM25Plus 在空语料上会除零崩溃（rank_bm25 内部
        avgdl = num_doc / corpus_size），空文档（质检不通过、无 chunk）
        必须提前跳过，不能假装建了索引。
        """
        if not document.chunks:
            return 0
        self._chunks.extend(document.chunks)
        tokenized = [tokenize(c.text) for c in self._chunks]
        self._bm25 = BM25Plus(tokenized)
        return len(document.chunks)

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """BM25 检索，返回得分 > 0 的 top_k 个相关 chunk。"""
        if self._bm25 is None or not self._chunks:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        results = []
        for i in ranked[:top_k]:
            if scores[i] <= 0:
                break
            results.append(SearchResult(chunk=self._chunks[i], score=scores[i]))
        return results

    def answer(self, query: str, top_k: int = 5) -> AnswerResult:
        """组装带编号引用的回答（阶段 B 为检索式回答，不调 LLM）。"""
        results = self.search(query, top_k)

        context_parts: list[str] = []
        citations: list[dict[str, Any]] = []
        for i, r in enumerate(results, 1):
            context_parts.append(f"[{i}] {r.chunk.text}")
            citations.append({
                "index": i,
                "source": r.chunk.metadata.get("source", ""),
                "source_type": r.chunk.metadata.get("source_type", ""),
                "page": r.chunk.metadata.get("page"),
                "block_type": r.chunk.metadata.get("block_type", "text"),
            })

        return AnswerResult(
            query=query,
            context="\n\n".join(context_parts),
            citations=citations,
            results=results,
        )
