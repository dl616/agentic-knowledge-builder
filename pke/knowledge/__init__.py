"""知识层：三层混合知识架构（查存互补）。

- rag.py：RAG 层（关键词/向量检索 + 带引用）。
- compile.py：Compile 层（LLM-Wiki 编译沉淀）。
- router.py：知识路由——冷热分层（摄取时）+ Wiki优先/RAG兜底（查询时）。
- memory.py：后续里程碑加入。
"""
from .compile import WikiPage, WikiStore
from .rag import AnswerResult, RagKnowledgeBase, SearchResult
from .router import RoutedAnswer, RouteDecision, Tier, classify_tier, query_route

__all__ = [
    "RagKnowledgeBase",
    "SearchResult",
    "AnswerResult",
    "WikiStore",
    "WikiPage",
    "RouteDecision",
    "RoutedAnswer",
    "Tier",
    "classify_tier",
    "query_route",
]
