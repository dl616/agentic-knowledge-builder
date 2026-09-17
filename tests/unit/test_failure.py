"""FailureAnalyzer（失败归因器）单测。

这是整个 S4 的核心验收：**故意制造两类失败，验证分流正确。**

    A. 故意改坏定位器 → 必须判为「元素失效」（机器自愈，不惊动人）
    B. 故意改业务规则 → 必须判为「业务变更」（报警给人）

如果这两条判反了，系统就废了：
    判反 A → 每次改版都报警，测试人员被噪音淹没
    判反 B → 真的业务缺陷被当成脚本问题自动修复，漏测

除了分流正确性，这里还验证「自愈」本身：
主定位器失效时，必须能靠备选策略把用例跑通，并记下实际用的是哪个策略。
"""
from __future__ import annotations

import pytest

from pke.testing.failure import (
    FailureAnalyzerAgent,
    classify,
    looks_like_environment_error,
    looks_like_locator_error,
    summarize,
)
from pke.testing.schemas import CaseResult, StepResult


def _result(
    *,
    ok: bool,
    steps: list[StepResult] | None = None,
    error: str = "",
    actual: str = "",
    case_id: str = "TC-1",
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        title="测试用例",
        ok=ok,
        steps=steps
        or [StepResult(action="click", target="注册", ok=ok, error=error)],
        actual_text=actual,
        error=error,
    )


# ---- 错误文本识别 ----


@pytest.mark.parametrize(
    "message",
    [
        "Timeout 30000ms exceeded.\nwaiting for locator(\"#submit\")",
        "Error: strict mode violation: get_by_role(\"button\") resolved to 3 elements",
        "waiting for get_by_label(\"手机号\") to be visible",
        "element is not visible",
    ],
)
def test_recognizes_locator_errors(message: str) -> None:
    assert looks_like_locator_error(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "net::ERR_CONNECTION_REFUSED at https://x",
        "Target closed",
        "Browser has been closed",
        "Navigation failed because page was closed",
    ],
)
def test_recognizes_environment_errors(message: str) -> None:
    assert looks_like_environment_error(message) is True


def test_normal_message_is_neither() -> None:
    assert looks_like_locator_error("页面未出现预期文本") is False
    assert looks_like_environment_error("页面未出现预期文本") is False


# ---- 分流 A：元素失效 ----


def test_stale_element_is_not_escalated_to_human() -> None:
    """改版导致定位不到 → 元素失效，机器自己处理，不要打扰人。"""
    result = _result(
        ok=False,
        steps=[
            StepResult(action="fill", target="手机号", ok=True,
                       strategy_expected="label", strategy_used="label"),
            StepResult(action="click", target="注册", ok=False,
                       error='Timeout 30000ms exceeded.\nwaiting for locator("#submit")',
                       strategy_expected="label"),
        ],
        error='Timeout 30000ms exceeded.\nwaiting for locator("#submit")',
    )

    report = classify(result)

    assert report.kind == "element_stale"
    assert report.needs_human is False, "元素失效不该惊动人——这是噪音的主要来源"
    assert report.should_update_knowledge is True, "但要更新知识库里的定位器"
    assert "注册" in report.evidence


def test_control_missing_from_model_is_element_stale() -> None:
    """控件在页面模型里都找不到了，同样是元素失效。"""
    result = _result(
        ok=False,
        steps=[StepResult(action="click", target="注册", ok=False,
                          error="页面模型里找不到控件「注册」，无法执行 click")],
    )
    report = classify(result)
    assert report.kind == "element_stale"
    assert report.needs_human is False


# ---- 分流 B：业务变更 ----


def test_business_change_escalates_to_human() -> None:
    """操作都成功、断言不成立 → 业务变了，必须让人判断。"""
    result = _result(
        ok=False,
        steps=[
            StepResult(action="fill", target="手机号", ok=True,
                       strategy_expected="label", strategy_used="label"),
            StepResult(action="click", target="注册", ok=True,
                       strategy_expected="label", strategy_used="label"),
            StepResult(action="assert_text", target="", ok=False,
                       error="页面未出现预期文本「注册成功」"),
        ],
        error="页面未出现预期文本「注册成功」",
        actual="用户名已存在",
    )

    report = classify(result)

    assert report.kind == "business_change"
    assert report.needs_human is True, "业务变更必须报警给人——是不是缺陷只有人能判断"
    assert report.should_update_knowledge is True
    assert "用户名已存在" in report.evidence, "证据里要带上页面实际内容，便于人判断"


def test_assert_url_failure_is_business_change() -> None:
    result = _result(
        ok=False,
        steps=[StepResult(action="assert_url", ok=False,
                          error="当前地址 https://x/login 不含「/home」")],
    )
    assert classify(result).kind == "business_change"


# ---- 分流 C：环境错误 ----


def test_environment_error_is_retryable() -> None:
    result = _result(
        ok=False,
        steps=[StepResult(action="click", target="注册", ok=False,
                          error="net::ERR_CONNECTION_REFUSED at https://x")],
    )

    report = classify(result)

    assert report.kind == "environment"
    assert report.needs_human is False
    assert report.should_update_knowledge is False, "环境问题不改资产，重跑就行"


# ---- 自愈识别 ----


def test_healed_step_is_reported_as_element_stale() -> None:
    """用例虽然过了，但有步骤靠降级才跑通——这也是元素失效的信号，要记下来。"""
    result = _result(
        ok=True,
        steps=[
            StepResult(action="fill", target="手机号", ok=True,
                       strategy_expected="label", strategy_used="placeholder"),
            StepResult(action="click", target="注册", ok=True,
                       strategy_expected="label", strategy_used="label"),
        ],
    )
    assert len(result.healed_steps) == 1

    report = classify(result)

    assert report.kind == "element_healed"
    assert report.needs_human is False
    assert report.should_update_knowledge is True, "要把 PageModel 的定位器改成实际生效的那个"
    assert "label" in report.evidence and "placeholder" in report.evidence


def test_clean_pass_produces_no_escalation() -> None:
    result = _result(
        ok=True,
        steps=[StepResult(action="click", target="注册", ok=True,
                          strategy_expected="label", strategy_used="label")],
    )
    report = classify(result)
    assert report.needs_human is False
    assert report.should_update_knowledge is False


# ---- StepResult 自愈判定 ----


def test_healed_property() -> None:
    assert StepResult(action="fill", ok=True,
                      strategy_expected="label", strategy_used="placeholder").healed is True
    assert StepResult(action="fill", ok=True,
                      strategy_expected="label", strategy_used="label").healed is False
    assert StepResult(action="fill", ok=False,
                      strategy_expected="label", strategy_used="placeholder").healed is False


# ---- Agent 契约与汇总 ----


def test_agent_only_reports_failures_and_healed() -> None:
    from pke.agents.base import AgentMessage

    clean = _result(ok=True, case_id="TC-ok",
                    steps=[StepResult(action="click", target="注册", ok=True,
                                      strategy_expected="label", strategy_used="label")])
    broken = _result(ok=False, case_id="TC-bad",
                     steps=[StepResult(action="click", target="注册", ok=False,
                                       error="waiting for locator")])

    out = FailureAnalyzerAgent().run(AgentMessage(payload=[clean, broken]))

    assert len(out.payload) == 1, "通过的用例不该出现在报告里"
    assert out.meta["total"] == 2
    assert out.meta["failed"] == 1
    assert out.meta["by_kind"]["element_stale"] == 1


def test_agent_accepts_single_result() -> None:
    from pke.agents.base import AgentMessage

    out = FailureAnalyzerAgent().run(AgentMessage(payload=_result(ok=True)))
    assert out.payload == []


def test_agent_rejects_wrong_payload() -> None:
    from pke.agents.base import AgentMessage

    with pytest.raises(TypeError, match="CaseResult"):
        FailureAnalyzerAgent().run(AgentMessage(payload="not a result"))


def test_summarize_separates_human_and_auto() -> None:
    reports = [
        classify(_result(ok=False, case_id="TC-biz",
                         steps=[StepResult(action="assert_text", ok=False,
                                           error="页面未出现预期文本「注册成功」")])),
        classify(_result(ok=False, case_id="TC-stale",
                         steps=[StepResult(action="click", target="注册", ok=False,
                                           error="waiting for locator")])),
    ]
    text = summarize(reports)

    assert "需人工确认 1 条" in text
    assert "可自动处置 1 条" in text
    assert "TC-biz" in text and "TC-stale" in text


def test_summarize_empty() -> None:
    assert "全部通过" in summarize([])
