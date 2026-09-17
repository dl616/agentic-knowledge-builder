"""执行器与失败归因的浏览器集成测试。

这是 S4 的验收核心，验证三个真实场景：

    ┌────────────────────────────┬──────────────────┬────────────┐
    │ 场景                       │ 期望结果         │ 是否惊动人 │
    ├────────────────────────────┼──────────────────┼────────────┤
    │ v1 用例 跑 v1 页           │ 通过，无降级     │ 否         │
    │ v1 用例 跑 v2 页（改版）   │ 自愈通过，有降级 │ 否（但更新资产）│
    │ v1 用例 跑 v3 页（业务变） │ 断言失败         │ **是**     │
    └────────────────────────────┴──────────────────┴────────────┘

第三条最重要：**如果业务变更被误判成元素失效，就是漏测。**
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pke.agents.base import AgentMessage
from pke.testing.analyzer import AnalyzerAgent
from pke.testing.executor import CaseExecutor, run_case
from pke.testing.explorer import ExplorerAgent
from pke.testing.failure import FailureAnalyzerAgent, classify
from pke.testing.generator import CaseGeneratorAgent
from pke.testing.schemas import PageModel, TestCase, TestStep

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
V1_URL = (FIXTURES / "signup.html").resolve().as_uri()
V2_URL = (FIXTURES / "signup_v2_relayout.html").resolve().as_uri()
V3_URL = (FIXTURES / "signup_v3_business_change.html").resolve().as_uri()


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


@pytest.fixture(scope="module")
def v1_model() -> PageModel:
    """用真实浏览器探索 v1 页面得到的页面模型。"""
    snap = ExplorerAgent(headless=True).explore(V1_URL)
    return AnalyzerAgent().run(AgentMessage(payload=snap)).payload


@pytest.fixture(scope="module")
def happy_case(v1_model: PageModel) -> TestCase:
    cases = CaseGeneratorAgent().run(AgentMessage(payload=v1_model)).payload
    return next(c for c in cases if c.category == "正常流程")


# ---- 场景一：v1 用例跑 v1 页，应当干净通过 ----


def test_happy_path_passes_on_v1(v1_model: PageModel, happy_case: TestCase) -> None:
    results = CaseExecutor().run([happy_case], v1_model)
    result = results[0]

    assert result.ok, f"用例未通过：{result.error}"
    assert not result.healed_steps, "原页面上不该发生定位降级"
    assert "注册成功" in result.actual_text


# ---- 场景二：v1 用例跑 v2 改版页，应当自愈通过 ----


def test_self_heals_after_relayout(v1_model: PageModel, happy_case: TestCase) -> None:
    """改版后靠备选定位策略跑通——这正是自动化维护成本能被压下来的原因。"""
    results = CaseExecutor().run([happy_case], v1_model, url_override=V2_URL)
    result = results[0]

    assert result.ok, f"自愈失败：{result.error}"
    assert result.healed_steps, "应当有步骤靠备选策略才跑通（否则说明 v2 没起到改版的作用）"
    assert "注册成功" in result.actual_text


def test_healing_is_reported_as_element_issue(v1_model: PageModel, happy_case: TestCase) -> None:
    """自愈通过了，仍需上报：资产里的定位器要更新成实际生效的那个。"""
    results = CaseExecutor().run([happy_case], v1_model, url_override=V2_URL)
    report = classify(results[0])

    assert report.kind == "element_healed"
    assert report.needs_human is False, "自愈成功不该惊动人"
    assert report.should_update_knowledge is True, "但要把稳的定位器写回知识库"


def test_healing_records_which_strategy_worked(
    v1_model: PageModel, happy_case: TestCase
) -> None:
    """降级记录必须包含「从哪个策略 → 到哪个策略」，否则没法更新资产。"""
    results = CaseExecutor().run([happy_case], v1_model, url_override=V2_URL)
    healed = results[0].healed_steps

    assert healed, "没有发生降级"
    for step in healed:
        assert step.strategy_expected, "缺少原策略"
        assert step.strategy_used, "缺少实际生效策略"
        assert step.strategy_used != step.strategy_expected


# ---- 场景三：v1 用例跑 v3 业务变更页，应当报警给人 ----


def test_business_change_fails_assertion(v1_model: PageModel, happy_case: TestCase) -> None:
    results = CaseExecutor().run([happy_case], v1_model, url_override=V3_URL)
    result = results[0]

    assert not result.ok, "业务变更页上，用例应当失败"
    # 关键：失败发生在断言步骤，而不是定位步骤
    failed = result.failed_step
    assert failed is not None and failed.action == "assert_text"


def test_business_change_is_escalated_to_human(
    v1_model: PageModel, happy_case: TestCase
) -> None:
    """业务变更必须报警给人 —— 判错就是漏测。"""
    results = CaseExecutor().run([happy_case], v1_model, url_override=V3_URL)
    report = classify(results[0])

    assert report.kind == "business_change", f"误判为 {report.kind}，这会导致漏测"
    assert report.needs_human is True
    assert "注册申请已提交" in report.evidence, "证据里要带上页面实际内容，便于人判断"


def test_business_change_is_not_confused_with_element_issue(
    v1_model: PageModel, happy_case: TestCase
) -> None:
    """v3 的控件一个没动，所以不该有任何定位降级。

    这条断言把「业务变更」和「元素失效」彻底区分开：
    元素都在（无降级），只是预期不对 → 只能是业务变了。
    """
    results = CaseExecutor().run([happy_case], v1_model, url_override=V3_URL)
    assert not results[0].healed_steps, "v3 未改控件，不该发生定位降级"


# ---- 场景四：控件真的没了 → 元素失效 ----


def test_missing_control_is_element_stale(v1_model: PageModel) -> None:
    """控件彻底消失时，所有定位策略都失败 → 元素失效，不惊动人。"""
    # 手工构造步骤：生成器只会产出页面上真实存在的控件，造不出「控件消失」的场景
    case = TestCase(
        id="TC-ghost",
        title="点击一个不存在的按钮",
        steps=[TestStep(action="click", target="这个控件不存在")],
    )

    results = CaseExecutor().run([case], v1_model)
    report = classify(results[0])

    assert report.kind == "element_stale"
    assert report.needs_human is False


# ---- 批量执行与汇总 ----


def test_batch_run_covers_all_cases(v1_model: PageModel) -> None:
    """全部 10 条用例一起跑，验证批量执行不互相污染。"""
    cases = CaseGeneratorAgent().run(AgentMessage(payload=v1_model)).payload
    results = CaseExecutor().run(cases, v1_model)

    assert len(results) == len(cases)

    passed = [r for r in results if r.ok]
    # v1 页面上：正常流程 + 边界值(8位) 应通过；异常校验类应失败（被前端拦截，断言仍成立）
    # 异常校验用例断言「出现手机号」等提示，前端确实会提示，所以也应通过
    assert len(passed) >= 8, (
        f"通过 {len(passed)}/{len(results)}，失败明细：\n"
        + "\n".join(f"  · {r.case_id}: {r.error[:80]}" for r in results if not r.ok)
    )


def test_negative_cases_are_intercepted_by_page(v1_model: PageModel) -> None:
    """异常用例的价值验证：填非法值后，页面确实拦截了并给出提示。

    这说明生成的用例不是「自说自话」，而是真的在验证页面行为。
    """
    cases = CaseGeneratorAgent().run(AgentMessage(payload=v1_model)).payload
    # 用例 ID 用语义槽位（phone）而不是控件字面名，改版后仍能稳定命中
    invalid = next(c for c in cases if c.id == "TC-phone-format-invalid")

    result = CaseExecutor().run([invalid], v1_model)[0]

    assert result.ok, f"异常用例应通过（页面拦截即预期）：{result.error}"
    assert "手机号" in result.actual_text, "页面未给出手机号相关提示"


def test_run_case_accepts_url_override(v1_model: PageModel, happy_case: TestCase) -> None:
    """url_override 参数本身要生效（否则前面的跨版本测试全是假象）。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        result = run_case(page, happy_case, v1_model, url_override=V2_URL)
        browser.close()

    # v2 页面标题与 v1 相同，但元素是 placeholder 风格；
    # 用断言「自愈发生」来证明确实跑在 v2 上
    assert result.healed_steps, "url_override 未生效，可能仍跑在 v1 上"


def test_failure_analyzer_agent_on_batch(v1_model: PageModel) -> None:
    """Agent 契约层：批量结果 → 归因报告，统计口径要正确。"""
    cases = CaseGeneratorAgent().run(AgentMessage(payload=v1_model)).payload
    results = CaseExecutor().run(cases, v1_model, url_override=V3_URL)

    out = FailureAnalyzerAgent().run(AgentMessage(payload=results))

    assert out.meta["total"] == len(cases)
    # v3 上所有用到「注册成功」断言的通过类用例都会失败
    assert out.meta["failed"] >= 2
    assert out.meta["by_kind"]["business_change"] >= 1
    assert out.meta["needs_human"] >= 1
