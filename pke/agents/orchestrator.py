"""Orchestrator：总控 Agent，把四个孤立 Agent 调度成完整流水线。

这是本轮升级的核心缺口修复。诊断发现：Ingest/Index/Retrieval/Answer 四个
Agent 之前是四段孤立脚本，没有任何东西真正"调度"它们——PRD 写"总控 Agent"，
代码里根本不存在。这里补上。

调度逻辑（摄取 pipeline，对应专家框架的「理解→设计→执行」三段）：

    1. Ingest    —— 摄取理解：识别类型、解析成 Document
    2. Quality   —— 质量判断：这份内容干不干净
    3. Router    —— 知识规划：该进 Wiki（热）还是只进 RAG（冷）
    4. Index     —— 总是索引进 RAG（保证可检索，无论冷热）
    5. Compile   —— 仅 hot 分层才编译进 Wiki（对应"冷热分层"）

查询走另一条路径（对应专家框架的"Wiki 优先、RAG 兜底"）：
    Router.query_route → 优先查 Wiki，未命中落到 RAG 检索。

Orchestrator 本身不做业务逻辑，只做编排——所有判断都下沉到各个 Agent /
Router 里，可独立测试。这是 Orchestrator-Worker 模式的核心约束。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..knowledge import RagKnowledgeBase, WikiStore
from ..knowledge.router import RoutedAnswer, RouteDecision, classify_tier, query_route
from ..schemas import Document
from .answer import AnswerAgent
from .base import AgentMessage
from .compile import CompileAgent
from .index import IndexAgent
from .quality import QualityAgent
from .retrieval import RetrievalAgent


@dataclass
class IngestReport:
    """一次「摄取 → 质检 → 路由 → 索引 → (可能)编译」的完整报告，全程可审计。"""
    document: Document
    quality_passed: bool
    quality_issues: list[str] = field(default_factory=list)
    route: RouteDecision | None = None
    indexed_chunks: int = 0
    compiled_path: str | None = None


class Orchestrator:
    """总控 Agent：识别、规划、调度四个专项 Agent。

    构造时注入知识层的两个存储（RAG 知识库 + Wiki 存储），
    内部持有各专项 Agent，对外只暴露两个动作：ingest_document / ask。
    """

    def __init__(self, wiki_dir: str | Path) -> None:
        self.kb = RagKnowledgeBase()
        self.wiki = WikiStore(Path(wiki_dir))

        self._quality = QualityAgent()
        self._index = IndexAgent(self.kb)
        self._compile = CompileAgent(self.wiki)
        self._retrieval = RetrievalAgent(self.kb)
        self._answer = AnswerAgent(self.kb)

    def ingest_document(self, document: Document) -> IngestReport:
        """调度「质检 → 路由 → 索引 → (可能)编译」，返回全程报告。

        这是本轮升级的关键动作：document 不再"来什么都无条件编译进 Wiki"，
        而是先质检、再由 Router 判断冷热，只有"热"文档才真正编译进 Wiki。
        """
        # 1. 质检：这份内容干不干净
        quality_msg = self._quality.run(AgentMessage(payload=document))
        quality_passed = bool(quality_msg.meta["passed"])
        quality_issues = quality_msg.meta["issues"]

        # 2. 索引：无论冷热，都要能被检索到（RAG 兜底的前提）
        index_msg = self._index.run(AgentMessage(payload=document))
        indexed = int(index_msg.meta["chunk_count"])

        # 3. 路由：这份文档该不该编译进 Wiki
        route = classify_tier(document, quality_passed=quality_passed)

        # 4. 仅 hot 分层才编译进 Wiki（这是"冷热分层"从 PRD 落到代码的地方）
        compiled_path: str | None = None
        if route.tier == "hot":
            compile_msg = self._compile.run(AgentMessage(payload=document))
            compiled_path = compile_msg.payload

        return IngestReport(
            document=document,
            quality_passed=quality_passed,
            quality_issues=quality_issues,
            route=route,
            indexed_chunks=indexed,
            compiled_path=compiled_path,
        )

    def ask(self, query: str, *, top_k: int = 5) -> RoutedAnswer:
        """调度「Wiki 优先、RAG 兜底」的查询路由。"""
        return query_route(self.wiki, self.kb, query, top_k=top_k)
