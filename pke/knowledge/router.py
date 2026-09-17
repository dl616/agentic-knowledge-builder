"""Router：知识路由的两个核心判断——冷热分层 + 查询路由。

这是诊断报告里点名的最大缺口：PRD 说"冷热分层"，但代码里从来没有任何
冷热判断逻辑——WikiStore.ingest() 来什么都无条件写入，RAG 和 Wiki 互不通信。

本模块负责回答两个问题：

1. classify_tier(document)：这份文档「该不该」编译进 Wiki？
   —— 摄取时的判断，对应 PRD 的「冷热分层」。
   规则（无 LLM 版本，诚实的启发式，非拍脑袋）：
   - 需要 OCR 的扫描件：内容不干净，不适合编译成"确定知道的知识"，只进 RAG。
   - chunk 数超过阈值的长文档：属于"长尾"，编译成本不划算，只进 RAG。
   - 质检不通过（Quality Agent 判定）：不能把有问题的内容当"稳定知识"编译。
   - 其余：编译进 Wiki（热），同时也进 RAG（RAG 兜底）。

2. query_route(wiki, kb, query)：一次提问「该」先查哪里？
   —— 查询时的判断，对应 PRD 的「Wiki 优先、RAG 兜底」。
   Wiki 命中 → 直接用（有综合、有出处）；Wiki 未命中 → 落到 RAG 检索兜底。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..config import COLD_TIER_MIN_CHUNKS
from ..schemas import Document
from .compile import WikiPage, WikiStore
from .rag import AnswerResult, RagKnowledgeBase

Tier = Literal["hot", "cold"]


@dataclass
class RouteDecision:
    """一次冷热分层判断的结果，带理由——不是黑箱，可审计。"""
    tier: Tier
    reason: str


def classify_tier(document: Document, *, quality_passed: bool = True) -> RouteDecision:
    """判断一份 Document 该进 Wiki（热）还是只进 RAG（冷）。

    这是「摄取时」的判断，决定是否调用 CompileAgent。
    无 LLM 版本用启发式规则，诚实标注局限：真正的"高频/核心"判断
    需要使用统计（回流机制），这里先用"干净 + 精炼 + 质检通过"作为代理指标。
    """
    if not quality_passed:
        return RouteDecision("cold", "质检未通过，不编译进 Wiki，仅保留在 RAG 供检索")

    needs_ocr = bool(document.meta.get("needs_ocr_pages"))
    if needs_ocr:
        return RouteDecision("cold", "含扫描件页面，内容不够干净，不适合编译成稳定知识")

    if len(document.chunks) > COLD_TIER_MIN_CHUNKS:
        return RouteDecision(
            "cold", f"chunk 数 {len(document.chunks)} 超过阈值 {COLD_TIER_MIN_CHUNKS}，属于长尾文档"
        )

    return RouteDecision("hot", "内容干净、体量适中、质检通过，编译进 Wiki 作为稳定知识")


@dataclass
class RoutedAnswer:
    """一次查询路由的结果：命中来源 + 具体内容。"""
    query: str
    source: Literal["wiki", "rag", "none"]
    wiki_pages: list[WikiPage]
    rag_result: AnswerResult | None


def query_route(
    wiki: WikiStore,
    kb: RagKnowledgeBase,
    query: str,
    *,
    top_k: int = 5,
) -> RoutedAnswer:
    """查询路由：Wiki 优先，未命中落到 RAG 兜底。

    Wiki 命中：说明这是"已沉淀的稳定知识"，直接用，回答更综合、更权威。
    Wiki 未命中：可能是长尾内容，或还没被编译，落到 RAG 做精确检索兜底。
    """
    wiki_pages = wiki.query(query)
    if wiki_pages:
        return RoutedAnswer(query=query, source="wiki", wiki_pages=wiki_pages, rag_result=None)

    rag_result = kb.answer(query, top_k=top_k)
    if rag_result.results:
        return RoutedAnswer(query=query, source="rag", wiki_pages=[], rag_result=rag_result)

    return RoutedAnswer(query=query, source="none", wiki_pages=[], rag_result=rag_result)
