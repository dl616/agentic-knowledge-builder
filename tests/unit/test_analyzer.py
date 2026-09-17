"""Analyzer（分析器）单元测试。

用「已知内容样本断言法」：fixture 注册页有 6 个已知控件，
这里手工构造出同样结构的 PageSnapshot，断言分析结果的每一项。
不依赖浏览器、不依赖网络、不依赖 LLM。
"""
from __future__ import annotations

import pytest

from pke.agents.base import AgentMessage
from pke.testing.analyzer import (
    AnalyzerAgent,
    build_page_model,
    denoise,
    infer_actions,
)
from pke.testing.schemas import (
    BusinessAction,
    Control,
    Locator,
    PageModel,
    PageSnapshot,
)


def _control(
    name: str,
    control_type: str,
    strategy: str = "label",
    value: str = "",
    role: str = "",
    text: str = "",
    required: bool = False,
) -> Control:
    return Control(
        name=name,
        control_type=control_type,
        locator=Locator(strategy=strategy, role=role, name=name, value=value),
        text=text,
        required=required,
    )


def _signup_snapshot() -> PageSnapshot:
    """构造与 tests/fixtures/signup.html 结构一致的快照。"""
    return PageSnapshot(
        url="file:///tests/fixtures/signup.html",
        title="用户注册",
        a11y_tree='textbox "手机号"\ntextbox "验证码"\nbutton "获取验证码"',
        controls=[
            _control("手机号", "textbox", value="手机号", role="textbox", required=True),
            _control("验证码", "textbox", value="验证码", role="textbox", required=True),
            _control("获取验证码", "button", strategy="text", value="获取验证码", role="button",
                     text="获取验证码"),
            _control("密码", "password", value="密码", required=True),
            _control("我已阅读并同意《用户协议》", "checkbox", value="我已阅读并同意《用户协议》",
                     required=True),
            _control("注册", "button", strategy="text", value="注册", role="button", text="注册"),
        ],
    )


# ---- Locator 定位器 ----


def test_locator_to_playwright_for_each_strategy() -> None:
    assert Locator(strategy="role", role="textbox", name="手机号").to_playwright() == (
        'get_by_role("textbox", name="手机号")'
    )
    assert Locator(strategy="label", name="手机号").to_playwright() == 'get_by_label("手机号")'
    assert Locator(strategy="testid", value="phone").to_playwright() == 'get_by_test_id("phone")'
    assert Locator(strategy="placeholder", value="请输入手机号").to_playwright() == (
        'get_by_placeholder("请输入手机号")'
    )
    assert Locator(strategy="text", value="注册").to_playwright() == 'get_by_text("注册")'
    assert Locator(strategy="css", value="#phone").to_playwright() == 'locator("#phone")'


def test_locator_stability_ranking() -> None:
    """role 比 css 稳定，稳定性评分应更小。"""
    assert Locator(strategy="role").stability < Locator(strategy="css").stability


def test_invalid_locator_strategy_raises() -> None:
    with pytest.raises(ValueError, match="未知定位策略"):
        Locator(strategy="xpath", value="//input")


def test_invalid_control_type_raises() -> None:
    with pytest.raises(ValueError, match="未知控件类型"):
        Control(name="x", control_type="slider", locator=Locator(strategy="css", value="#x"))


# ---- 去噪 ----


def test_denoise_drops_unknown_without_text() -> None:
    controls = [
        _control("手机号", "textbox"),
        Control(
            name="装饰块",
            control_type="unknown",
            locator=Locator(strategy="css", value="#ad"),
        ),
    ]
    assert [c.name for c in denoise(controls)] == ["手机号"]


def test_denoise_drops_nameless_and_duplicates() -> None:
    controls = [
        _control("手机号", "textbox"),
        _control("手机号", "textbox"),  # 重复
        Control(name="", control_type="button", locator=Locator(strategy="css", value="#b")),
    ]
    assert [c.name for c in denoise(controls)] == ["手机号"]


# ---- 动作推断 ----


def test_infer_actions_groups_inputs_into_submit() -> None:
    actions = infer_actions(_signup_snapshot().controls)
    submit = next(a for a in actions if a.name == "注册")

    assert submit.action_type == "submit"
    # 提交动作应把三个输入框 + 必填勾选 + 按钮本身都收拢进来
    assert "手机号" in submit.control_names
    assert "验证码" in submit.control_names
    assert "密码" in submit.control_names
    assert "我已阅读并同意《用户协议》" in submit.control_names
    assert submit.control_names[-1] == "注册"


def test_infer_actions_classifies_query_button() -> None:
    actions = infer_actions(_signup_snapshot().controls)
    send_code = next(a for a in actions if a.name == "获取验证码")

    assert send_code.action_type == "query"
    assert send_code.control_names == ["获取验证码"]


def test_submit_action_ignores_optional_checkbox() -> None:
    """非必填的勾选框不应被卷进提交动作（避免生成无用步骤）。"""
    controls = [
        _control("邮箱", "textbox", required=True),
        _control("订阅推送", "checkbox", required=False),
        _control("提交", "button", strategy="text", value="提交", text="提交"),
    ]
    submit = next(a for a in infer_actions(controls) if a.name == "提交")
    assert "订阅推送" not in submit.control_names


def test_invalid_action_type_raises() -> None:
    with pytest.raises(ValueError, match="未知动作类型"):
        BusinessAction(name="x", action_type="explode")


# ---- 页面建模 ----


def test_build_page_model_detects_signup_purpose() -> None:
    model = build_page_model(_signup_snapshot())

    assert model.purpose == "注册", "标题与按钮都含『注册』，应识别为注册页"
    assert model.title == "用户注册"
    assert len(model.controls) == 6
    # 6 个控件推导出 3 个业务动作：注册(submit)、获取验证码(query)、协议勾选(toggle)
    assert len(model.actions) == 3


def test_build_page_model_records_denoise_stats() -> None:
    snapshot = _signup_snapshot()
    snapshot.controls.append(
        Control(
            name="幽灵控件",
            control_type="unknown",
            locator=Locator(strategy="css", value="#g"),
        ),
    )
    model = build_page_model(snapshot)

    assert model.meta["source_snapshot_controls"] == 7
    assert model.meta["denoised_controls"] == 6, "未知类型且无文本的控件应被剔除"


def test_purpose_falls_back_to_empty_when_unknown() -> None:
    snapshot = PageSnapshot(
        url="https://example.com/abc",
        title="某个页面",
        controls=[_control("输入框", "textbox")],
    )
    assert build_page_model(snapshot).purpose == ""


def test_page_model_helpers() -> None:
    model = build_page_model(_signup_snapshot())

    assert model.get_control("密码") is not None
    assert model.get_control("不存在的控件") is None
    assert [c.name for c in model.input_controls] == ["手机号", "验证码", "密码"]
    assert "注册" in [c.name for c in model.clickable_controls]


def test_page_model_to_markdown_contains_control_table() -> None:
    markdown = build_page_model(_signup_snapshot()).to_markdown()

    assert "# 用户注册" in markdown
    assert "| 名称 | 类型 | 定位方式 | 必填 |" in markdown
    assert "手机号" in markdown
    assert "## 业务动作" in markdown


# ---- Agent 契约 ----


def test_analyzer_agent_returns_agent_message() -> None:
    agent = AnalyzerAgent()
    result = agent.run(AgentMessage(payload=_signup_snapshot()))

    assert isinstance(result, AgentMessage)
    assert isinstance(result.payload, PageModel)
    assert result.meta["agent"] == "analyzer"
    assert result.meta["purpose"] == "注册"
    assert result.meta["controls"] == 6


def test_analyzer_agent_rejects_wrong_payload() -> None:
    with pytest.raises(TypeError, match="PageSnapshot"):
        AnalyzerAgent().run(AgentMessage(payload="不是快照"))
