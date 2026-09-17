"""CaseGenerator（用例生成器）单测。

验证方法还是「已知内容样本断言法」：造一个和 fixture 一致的 PageModel，
里面的控件是预先已知的，所以「该生成几条、分别属于哪类」也是已知的。

重点不是「能生成」，而是「生成得对」——
必填项为空要每个必填框一条、格式非法要用非法值、边界值要卡在 8 位。
"""
from __future__ import annotations

import pytest

from pke.agents.base import AgentMessage
from pke.testing.generator import (
    CaseGeneratorAgent,
    _llm_enhance,
    find_submit_control,
    generate_cases,
    match_field_rule,
)
from pke.testing.schemas import (
    BusinessAction,
    Control,
    Locator,
    PageModel,
    TestCase,
    TestStep,
)


def _control(
    name: str,
    control_type: str,
    *,
    required: bool = False,
    element_id: str = "",
) -> Control:
    return Control(
        name=name,
        control_type=control_type,
        locator=Locator(strategy="label", name=name),
        text=name,
        required=required,
        meta={"id": element_id or name},
    )


@pytest.fixture()
def signup_model() -> PageModel:
    """与 tests/fixtures/signup.html 对应的页面模型。"""
    phone = _control("手机号", "textbox", required=True, element_id="phone")
    code = _control("验证码", "textbox", required=True, element_id="code")
    password = _control("密码", "password", required=True, element_id="password")
    agree = _control("我已阅读并同意《用户协议》", "checkbox", required=True, element_id="agree")
    submit = _control("注册", "button", element_id="submit")

    return PageModel(
        url="file:///tmp/signup.html",
        title="用户注册",
        purpose="注册",
        controls=[phone, code, password, agree, submit],
        actions=[
            BusinessAction(
                name="提交注册",
                action_type="submit",
                control_names=["手机号", "验证码", "密码", "我已阅读并同意《用户协议》", "注册"],
                description="填写完整信息后提交注册",
            )
        ],
    )


# ---- 字段规则匹配 ----


def test_match_phone_by_name() -> None:
    rule = match_field_rule(_control("手机号", "textbox", element_id="phone"))
    assert rule is not None and rule.key == "phone"


def test_match_code_by_name() -> None:
    rule = match_field_rule(_control("验证码", "textbox", element_id="code"))
    assert rule is not None and rule.key == "code"


def test_match_password_falls_back_to_control_type() -> None:
    """即使名字里没有「密码」，password 类型的控件也必须识别为密码字段。"""
    rule = match_field_rule(_control("pwd-field", "password", element_id="p"))
    assert rule is not None and rule.key == "password"


def test_match_returns_none_for_plain_textbox() -> None:
    assert match_field_rule(_control("备注", "textbox", element_id="note")) is None


def test_find_submit_control_prefers_action(signup_model: PageModel) -> None:
    control = find_submit_control(signup_model)
    assert control is not None and control.name == "注册"


def test_find_submit_control_falls_back_to_text() -> None:
    """没有 submit 动作时，按按钮文案兜底。"""
    model = PageModel(
        url="u",
        controls=[_control("重置", "button"), _control("登录", "button")],
    )
    control = find_submit_control(model)
    assert control is not None and control.name == "登录"


# ---- 生成结果 ----


def test_generates_expected_case_count(signup_model: PageModel) -> None:
    """注册页应生成 10 条：1 正常 + 3 必填空 + 3 格式非法 + 2 边界 + 1 未勾选。"""
    cases = generate_cases(signup_model)
    assert len(cases) == 10, [c.id for c in cases]


def test_happy_path_covers_all_inputs(signup_model: PageModel) -> None:
    cases = generate_cases(signup_model)
    happy = cases[0]

    assert happy.priority == "P0"
    assert happy.category == "正常流程"

    filled = {s.target for s in happy.steps if s.action == "fill"}
    assert filled == {"手机号", "验证码", "密码"}

    checked = {s.target for s in happy.steps if s.action == "check"}
    assert checked == {"我已阅读并同意《用户协议》"}

    assert any(s.action == "click" and s.target == "注册" for s in happy.steps)
    assert "注册成功" in happy.expected


def test_missing_required_one_case_per_field(signup_model: PageModel) -> None:
    """三个必填输入各出一条「留空」用例，勾选框不算输入。"""
    cases = [c for c in generate_cases(signup_model) if c.category == "异常校验"]
    empty_cases = [c for c in cases if c.id.endswith("-required-empty")]

    assert len(empty_cases) == 3
    assert {c.id for c in empty_cases} == {
        "TC-phone-required-empty",
        "TC-code-required-empty",
        "TC-password-required-empty",
    }


def test_required_empty_case_skips_that_field(signup_model: PageModel) -> None:
    """「手机号留空」的用例里，步骤中绝不能出现给手机号填值。"""
    cases = generate_cases(signup_model)
    case = next(c for c in cases if c.id == "TC-phone-required-empty")

    filled = {s.target for s in case.steps if s.action == "fill"}
    assert "手机号" not in filled
    assert filled == {"验证码", "密码"}


def test_format_invalid_uses_invalid_values(signup_model: PageModel) -> None:
    """格式非法用例必须填**非法值**，且说明为什么非法。"""
    cases = [c for c in generate_cases(signup_model) if c.id.endswith("-format-invalid")]

    assert len(cases) == 3
    by_id = {c.id: c for c in cases}

    phone_step = next(
        s for s in by_id["TC-phone-format-invalid"].steps
        if s.action == "fill" and s.target == "手机号"
    )
    assert phone_step.value == "12345"
    assert "11 位" in by_id["TC-phone-format-invalid"].expected

    pwd_step = next(
        s for s in by_id["TC-password-format-invalid"].steps
        if s.action == "fill" and s.target == "密码"
    )
    assert pwd_step.value == "123"


def test_boundary_cases_straddle_the_limit(signup_model: PageModel) -> None:
    """边界值要卡在最短长度两侧：8 位通过、7 位拦截。"""
    cases = [c for c in generate_cases(signup_model) if c.category == "边界值"]

    assert len(cases) == 2
    passing = next(c for c in cases if "成功" in c.expected)
    failing = next(c for c in cases if "拦截" in c.expected)

    pass_value = next(s.value for s in passing.steps if s.action == "fill" and s.target == "密码")
    fail_value = next(s.value for s in failing.steps if s.action == "fill" and s.target == "密码")
    assert len(pass_value) == 8
    assert len(fail_value) == 7


def test_unchecked_agreement_case(signup_model: PageModel) -> None:
    cases = [c for c in generate_cases(signup_model) if c.id.endswith("-unchecked")]

    assert len(cases) == 1
    case = cases[0]
    assert not any(s.action == "check" for s in case.steps), "未勾选用例不该有勾选步骤"
    # 其余输入仍要填合法值，否则测的就不是「没勾协议」了
    assert {s.target for s in case.steps if s.action == "fill"} == {"手机号", "验证码", "密码"}


def test_case_ids_are_unique(signup_model: PageModel) -> None:
    ids = [c.id for c in generate_cases(signup_model)]
    assert len(ids) == len(set(ids))


# ---- 历史资产复用 ----


def test_history_overrides_generated_case(signup_model: PageModel) -> None:
    """历史用例（人工审核过的）优先级高于新生成的——人工修改不能被覆盖掉。"""
    reviewed = TestCase(
        id="TC-phone-required-empty",
        title="【人工修订】手机号留空应提示具体格式要求",
        priority="P0",
        category="异常校验",
        steps=[TestStep(action="fill", target="验证码", value="123456")],
        expected="提示「请输入正确的手机号」",
        source="history",
    )
    cases = generate_cases(signup_model, history=[reviewed])

    case = next(c for c in cases if c.id == "TC-phone-required-empty")
    assert case.title == "【人工修订】手机号留空应提示具体格式要求"
    assert case.source == "history"
    assert len(cases) == 10, "复用不该改变用例总数"


# ---- 无提交按钮的页面不该崩 ----


def test_page_without_submit_still_generates() -> None:
    model = PageModel(url="u", purpose="展示", controls=[_control("手机号", "textbox")])
    cases = generate_cases(model)
    assert cases, "没有提交按钮也应至少产出正常流程用例"
    assert not any(s.action == "click" for s in cases[0].steps)


# ---- Agent 契约 ----


def test_agent_contract(signup_model: PageModel) -> None:
    result = CaseGeneratorAgent().run(AgentMessage(payload=signup_model))

    assert isinstance(result.payload, list)
    assert all(isinstance(c, TestCase) for c in result.payload)
    assert result.meta["cases"] == 10
    assert result.meta["llm_enabled"] is False
    assert result.meta["by_source"]["rule"] == 10


def test_agent_rejects_wrong_payload() -> None:
    with pytest.raises(TypeError, match="PageModel"):
        CaseGeneratorAgent().run(AgentMessage(payload="not a model"))


# ---- LLM 增强层的容错 ----


class _BrokenLLM:
    def complete(self, *_: object, **__: object) -> str:
        raise RuntimeError("网关不可达")


def test_llm_failure_degrades_gracefully(signup_model: PageModel) -> None:
    """LLM 挂了不能影响规则层产出——这是设计内的降级路径。"""
    cases = _llm_enhance(signup_model, _BrokenLLM(), generate_cases(signup_model))
    assert cases == []


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete(self, *_: object, **__: object) -> str:
        import json

        return json.dumps(self.payload)


def test_llm_cases_are_merged_and_tagged(signup_model: PageModel) -> None:
    llm = _FakeLLM(
        {
            "cases": [
                {
                    "title": "同一手机号重复注册",
                    "priority": "P1",
                    "category": "异常校验",
                    "steps": [{"action": "fill", "target": "手机号", "value": "13800138000"}],
                    "expected": "提示手机号已注册",
                }
            ]
        }
    )
    cases = CaseGeneratorAgent(llm=llm).generate(signup_model)

    assert len(cases) == 11
    extra = cases[-1]
    assert extra.source == "llm"
    assert extra.title == "同一手机号重复注册"
    assert extra.steps[0].target == "手机号"


def test_llm_invalid_json_is_ignored(signup_model: PageModel) -> None:
    class _GarbageLLM:
        def complete(self, *_: object, **__: object) -> str:
            return "这不是 JSON"

    cases = _llm_enhance(signup_model, _GarbageLLM(), generate_cases(signup_model))
    assert cases == []


def test_llm_illegal_priority_is_skipped(signup_model: PageModel) -> None:
    """LLM 返回不合法枚举值时，跳过该条而不是让整批失败。"""
    llm = _FakeLLM(
        {
            "cases": [
                {"title": "优先级写错", "priority": "P9", "steps": [], "expected": "x"},
                {"title": "正常的一条", "priority": "P2", "steps": [], "expected": "y"},
            ]
        }
    )
    cases = _llm_enhance(signup_model, llm, generate_cases(signup_model))

    assert len(cases) == 1
    assert cases[0].title == "正常的一条"
