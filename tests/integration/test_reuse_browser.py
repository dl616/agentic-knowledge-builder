"""跨版本复用的浏览器集成测试（S5 验收）。

这一条是「知识能不能攒住」的端到端证明：

    第一轮：探索 v1 → 生成用例 → 真实浏览器执行 → 沉淀进知识库
    第二轮：探索 v2（去掉 label 的改版页）→ 知识库召回历史用例
            → 按语义槽位重绑到新控件 → 跑 v2 页面

验收标准不是「跑通几条」，而是两条更硬的：

    1. 第二轮确实复用了第一轮的用例（来源里有 history，且不是 0 条）；
    2. 复用回来的用例在改版后的页面上真的能跑通（不是召回一堆跑不动的）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pke.agents.base import AgentMessage
from pke.testing.analyzer import AnalyzerAgent
from pke.testing.executor import CaseExecutor
from pke.testing.explorer import ExplorerAgent
from pke.testing.generator import CaseGeneratorAgent
from pke.testing.knowledge import TestKnowledgeBase
from pke.testing.schemas import PageModel

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
V1_URL = (FIXTURES / "signup.html").resolve().as_uri()
V2_URL = (FIXTURES / "signup_v2_relayout.html").resolve().as_uri()


def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _playwright_available(), reason="Playwright 或 Chromium 内核未安装"),
]


def _model_of(url: str) -> PageModel:
    """探索 + 建模，拿到该版本页面的 PageModel。"""
    snap = ExplorerAgent(headless=True).explore(url)
    return AnalyzerAgent().run(AgentMessage(payload=snap)).payload


@pytest.fixture(scope="module")
def two_rounds(tmp_path_factory: pytest.TempPathFactory):
    """跑完两轮闭环，返回（v2 用例, v2 执行结果, 知识库, 重绑记录）。"""
    kb = TestKnowledgeBase(wiki_dir=tmp_path_factory.mktemp("reuse_kb"))

    # ---- 第一轮：v1 从零生成 + 执行 + 沉淀 ----
    v1_model = _model_of(V1_URL)
    v1_cases = CaseGeneratorAgent().run(AgentMessage(payload=v1_model)).payload
    v1_results = CaseExecutor(headless=True).run(v1_cases, v1_model)
    kb.store_run_result(v1_model, v1_cases, v1_results)

    # ---- 第二轮：v2 先召回历史，再生成 ----
    v2_model = _model_of(V2_URL)
    history = kb.history_cases(v2_model)
    rebind_notes = list(kb.rebind_notes)
    v2_result = CaseGeneratorAgent().run(
        AgentMessage(payload=v2_model, meta={"history": history})
    )
    v2_cases = v2_result.payload
    v2_results = CaseExecutor(headless=True).run(v2_cases, v2_model)

    return {
        "v1_cases": v1_cases,
        "v1_results": v1_results,
        "v2_cases": v2_cases,
        "v2_results": v2_results,
        "by_source": v2_result.meta["by_source"],
        "rebind_notes": rebind_notes,
        "kb": kb,
    }


def test_round1_all_pass_on_own_page(two_rounds):
    """基线：第一轮用例在自己页面上应该全通过。"""
    results = two_rounds["v1_results"]
    assert len(results) >= 8
    assert all(r.ok for r in results), [r.title for r in results if not r.ok]


def test_round2_recalls_history_cases(two_rounds):
    """第二轮必须召回并复用第一轮的用例——这是「积累」的证明。"""
    assert two_rounds["by_source"].get("history", 0) > 0


def test_round2_rebinds_renamed_controls(two_rounds):
    """改版后控件名变了，重绑记录要如实反映（v1「手机号」→ v2「请输入手机号」）。"""
    notes = two_rounds["rebind_notes"]
    assert notes, "改版页应该触发语义重绑"
    assert any("→" in n for n in notes)


def test_round2_reused_cases_actually_run(two_rounds):
    """复用回来的用例在改版页上要真能跑通——召回一堆跑不动的等于没复用。"""
    results = two_rounds["v2_results"]
    passed = [r for r in results if r.ok]
    assert len(passed) >= len(results) * 0.6, (
        f"v2 只通过 {len(passed)}/{len(results)}："
        + "; ".join(f"{r.title} → {r.error}" for r in results if not r.ok)
    )


def test_case_ids_stable_between_rounds(two_rounds):
    """两轮用例 ID 一致：人工在第一轮做的审核/修改能延续到第二轮。"""
    v1_ids = {c.id for c in two_rounds["v1_cases"]}
    v2_ids = {c.id for c in two_rounds["v2_cases"]}
    assert v1_ids == v2_ids
