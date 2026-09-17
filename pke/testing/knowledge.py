"""测试知识层：把测试资产接进已有的 Compile（热层）+ RAG（冷层）。

为什么不另起炉灶：
    AKB 已经练成了「冷热分层 + Wiki 优先 RAG 兜底」的知识管理能力，
    测试资产本质也是一种知识，只是形态不同（PageModel、TestCase）。
    复用 WikiStore（编译沉淀）与 RagKnowledgeBase（检索增强），
    测试资产就自动获得了「沉淀 + 召回 + 溯源」三件套，
    不需要再写一套存储，也就不会出现第二份索引需要维护。

分层策略（与 Router 的冷热分层一致）：
    热层（Compile / Wiki）：PageModel——稳定、复用价值高、变更不频繁。
    冷层（RAG）：历史用例——数量大、长尾、按需检索，CaseGenerator 召回复用。

闭环价值：
    第一轮跑完 → 资产沉淀；第二轮进来 → CaseGenerator 先召回历史用例，
    生成得更快更全。这就是「积累复用」，也是这个系统区别于
    「一次性用例生成器」的根本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from ..knowledge.compile import WikiStore
from ..knowledge.rag import RagKnowledgeBase
from ..schemas import Document
from .executor import rebind_case
from .schemas import CaseResult, PageModel, TestCase

__all__ = ["TestKnowledgeBase", "RecallHit", "model_to_document", "case_to_document"]


def model_to_document(model: PageModel) -> Document:
    """PageModel → Document（可归档、可检索的知识单元）。

    拆 chunk 的原则：按「控件」和「业务动作」拆，而不是整页一个 chunk。
    因为召回是按控件名/动作名做的——「验证码」这条知识要能被单独命中，
    如果和整个页面糊在一起，检索粒度就太粗了。
    """
    doc = Document(
        source=model.url,
        source_type="test",
        title=f"页面模型：{model.title}",
        meta={
            "asset_type": "pagemodel",
            "control_count": len(model.controls),
            "action_count": len(model.actions),
        },
    )

    doc.add_chunk(
        f"页面「{model.title}」（{model.url}）共 {len(model.controls)} 个控件、"
        f"{len(model.actions)} 个业务动作。",
        block_type="summary",
        section="概览",
        asset_type="pagemodel",
        url=model.url,
    )

    for control in model.controls:
        doc.add_chunk(
            f"控件「{control.name}」：类型 {control.control_type}，"
            f"定位方式 {control.locator.strategy}={control.locator.value}。",
            block_type="control",
            section="控件",
            asset_type="pagemodel_control",
            control_name=control.name,
            control_type=control.control_type,
            url=model.url,
        )

    for action in model.actions:
        doc.add_chunk(
            f"业务动作「{action.name}」（{action.action_type}）："
            f"涉及 {'、'.join(action.control_names)}。"
            + (f" 说明：{action.description}" if action.description else ""),
            block_type="action",
            section="业务动作",
            asset_type="pagemodel_action",
            action_type=action.action_type,
            url=model.url,
        )

    return doc


def case_to_document(case: TestCase, *, model_url: str = "") -> Document:
    """TestCase → Document（冷层可检索单元）。

    正文要包含「用例做了什么」的语义，而不只是步骤机械拼接——
    检索时是用「新页面的控件名」去找「历史用例」，
    所以标题、控件名、预期结果都要能被分词命中。
    """
    steps_text = "；".join(step.describe() for step in case.steps)
    doc = Document(
        source=model_url or "unknown",
        source_type="test",
        title=f"用例：{case.title}",
        meta={
            "asset_type": "case",
            "case_id": case.id,
            "priority": case.priority,
            "category": case.category,
        },
    )
    doc.add_chunk(
        f"用例「{case.title}」（{case.category} / {case.priority}）。"
        f"步骤：{steps_text}。预期结果：{case.expected}",
        block_type="case",
        section="测试用例",
        asset_type="case",
        case_id=case.id,
        category=case.category,
        priority=case.priority,
    )
    return doc


@dataclass
class RecallHit:
    """一次召回的结果：命中的历史资产 + 得分 + 出处。"""

    text: str
    score: float
    asset_type: str = ""
    source: str = ""


@dataclass
class TestKnowledgeBase:
    """测试资产知识库：沉淀（写）+ 召回（读）。

    hot  : WikiStore        —— PageModel 稳定资产，Wiki 优先命中
    cold : RagKnowledgeBase —— 历史用例长尾，按需检索

    两者共用一套查询入口：先查热层（精准、已沉淀），
    不够再由调用方去冷层补（宽泛、全量）。
    """

    __test__: ClassVar[bool] = False  # 别让 pytest 把知识库当测试类收集

    wiki_dir: Path
    wiki: WikiStore = field(init=False)
    rag: RagKnowledgeBase = field(init=False)
    _stored_models: list[PageModel] = field(default_factory=list, init=False)
    _stored_cases: list[TestCase] = field(default_factory=list, init=False)
    # 用例 ID → 索引正文，召回回查时避免重复重建 Document
    _case_texts: dict[str, str] = field(default_factory=dict, init=False)
    # 最近一次召回的重绑记录（「手机号 → 请输入手机号」），对外可观测
    rebind_notes: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.wiki = WikiStore(Path(self.wiki_dir))
        self.rag = RagKnowledgeBase()

    # ---- 沉淀（写）----
    def store_page_model(self, model: PageModel) -> str:
        """PageModel 进热层（Wiki）+ 冷层（RAG），返回 wiki 相对路径。"""
        doc = model_to_document(model)
        rel_path = self.wiki.ingest(doc)
        self.rag.add(doc)
        self._stored_models.append(model)
        return rel_path

    def store_cases(self, cases: list[TestCase], *, model_url: str = "") -> int:
        """历史用例进冷层（RAG），返回新增 chunk 数。

        只有跑通的用例才值得沉淀——失败用例反映的是「当时页面有问题」，
        沉淀进去会污染召回结果。
        """
        added = 0
        for case in cases:
            doc = case_to_document(case, model_url=model_url)
            added += self.rag.add(doc)
            self._stored_cases.append(case)
            self._case_texts[case.id] = doc.chunks[0].text
        return added

    def store_run_result(
        self,
        model: PageModel,
        cases: list[TestCase],
        results: list[CaseResult],
    ) -> dict[str, int]:
        """一次执行结束后统一沉淀：PageModel 加热层，通过用例进冷层。"""
        self.store_page_model(model)
        passed_ids = {r.case_id for r in results if r.ok}
        passed_cases = [c for c in cases if c.id in passed_ids]
        added = self.store_cases(passed_cases, model_url=model.url)
        return {
            "pagemodel": 1,
            "cases_stored": len(passed_cases),
            "chunks_added": added,
        }

    # ---- 召回（读）----
    def recall(self, query: str, top_k: int = 5) -> list[RecallHit]:
        """按语义召回历史测试资产。"""
        hits: list[RecallHit] = []
        for r in self.rag.search(query, top_k=top_k):
            meta = r.chunk.metadata
            hits.append(
                RecallHit(
                    text=r.chunk.text,
                    score=r.score,
                    asset_type=str(meta.get("asset_type", "")),
                    source=str(meta.get("source", "")),
                )
            )
        return hits

    def recall_for_model(self, model: PageModel, top_k: int = 3) -> list[RecallHit]:
        """为新页面召回相关历史资产：按控件名 / 业务动作逐个查询后合并去重。

        这是 CaseGenerator「带着历史资产生成用例」的入口——
        拿到的是「过去在类似控件上设计过哪些用例」，
        而不是从零拍脑袋。
        """
        queries: list[str] = []
        for control in model.controls:
            queries.append(f"{control.name} {control.control_type}")
        for action in model.actions:
            queries.append(action.name)

        merged: dict[str, RecallHit] = {}
        for q in queries:
            for hit in self.recall(q, top_k=top_k):
                # 同一条资产被多个 query 命中时，保留最高分
                if hit.text not in merged or hit.score > merged[hit.text].score:
                    merged[hit.text] = hit

        # 不做截断：召回是给下游「挑复用对象」用的，
        # 提前砍掉会把本可复用的历史用例丢掉（v1 沉淀 10 条只回来 3 条就是这么来的）。
        return sorted(merged.values(), key=lambda h: h.score, reverse=True)

    def history_cases(self, model: PageModel, *, limit: int = 20) -> list[TestCase]:
        """召回可直接复用的历史用例对象（不是文本片段）。

        与 recall_for_model 的区别：那个返回「知识片段」给人看，
        这个返回「用例对象」给 CaseGenerator 用——
        按 ID 命中时直接用历史版本，测试人员上轮的修改不会被覆盖。
        这是「人工审核一次、后续持续复用」能成立的技术前提。
        """
        recalled_texts = {h.text for h in self.recall_for_model(model)}
        if not recalled_texts:
            return []

        self.rebind_notes = []
        matched: list[TestCase] = []
        for case in self._stored_cases:
            if self._case_texts.get(case.id) not in recalled_texts:
                continue
            # 关键一步：历史用例是按「上一版页面」写的，控件名对不上这一版。
            # 先按语义槽位重绑到当前页面模型，再交给 CaseGenerator——
            # 否则复用回来的用例一执行就「找不到控件」，等于没复用。
            rebound, notes = rebind_case(case, model)
            self.rebind_notes.extend(n for n in notes if n not in self.rebind_notes)
            matched.append(rebound)
            if len(matched) >= limit:
                break
        return matched

    # ---- 观测 ----
    @property
    def model_count(self) -> int:
        return len(self._stored_models)

    @property
    def case_count(self) -> int:
        return len(self._stored_cases)

    @property
    def chunk_count(self) -> int:
        return self.rag.chunk_count
