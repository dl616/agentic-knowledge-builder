"""Explorer（探索器）纯逻辑单元测试。

这里只测「浏览器抽出来的原始数据 → 控件对象」这段纯函数，
不启动浏览器（浏览器相关的集成测试在 tests/integration/ 下，需要装 Playwright）。
这样 CI 在没有浏览器的环境里也能跑。
"""
from __future__ import annotations

import pytest

from pke.testing.explorer import (
    choose_locator,
    choose_name,
    infer_control_type,
    parse_controls,
)
from pke.testing.schemas import Control, Locator, PageSnapshot


def _raw(**kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {"tag": "input", "type": "text", "id": "", "text": ""}
    base.update(kwargs)
    return base


# ---- 控件类型推断 ----


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"tag": "input", "type": "tel"}, "textbox"),
        ({"tag": "input", "type": "email"}, "textbox"),
        ({"tag": "input", "type": "text"}, "textbox"),
        ({"tag": "input", "type": "password"}, "password"),
        ({"tag": "input", "type": "checkbox"}, "checkbox"),
        ({"tag": "input", "type": "radio"}, "radio"),
        ({"tag": "input", "type": "file"}, "file"),
        ({"tag": "input", "type": "submit"}, "button"),
        ({"tag": "textarea"}, "textarea"),
        ({"tag": "select"}, "select"),
        ({"tag": "button"}, "button"),
        ({"tag": "a"}, "link"),
        ({"tag": "input"}, "textbox"),  # 没写 type，浏览器默认当 text
        ({"tag": "div", "role": "button"}, "button"),  # ARIA 自定义控件
        ({"tag": "span"}, "unknown"),
    ],
)
def test_infer_control_type(raw: dict[str, object], expected: str) -> None:
    assert infer_control_type(raw) == expected


# ---- 定位策略选择 ----


def test_locator_prefers_testid() -> None:
    locator = choose_locator(
        _raw(testid="phone-input", label_text="手机号", placeholder="请输入手机号"), "textbox"
    )
    assert locator.strategy == "testid"
    assert locator.value == "phone-input"


def test_locator_falls_back_to_label() -> None:
    locator = choose_locator(_raw(label_text="手机号", placeholder="请输入手机号"), "textbox")
    assert locator.strategy == "label"
    assert locator.name == "手机号"


def test_locator_uses_aria_label_when_no_visible_label() -> None:
    locator = choose_locator(_raw(aria_label="手机号"), "textbox")
    assert locator.strategy == "label"
    assert locator.name == "手机号"


def test_locator_uses_placeholder_when_no_label() -> None:
    locator = choose_locator(_raw(placeholder="请输入手机号"), "textbox")
    assert locator.strategy == "placeholder"


def test_locator_uses_role_for_buttons() -> None:
    locator = choose_locator(_raw(tag="button", text="注册"), "button")
    assert locator.strategy == "role"
    assert locator.role == "button"
    assert locator.name == "注册"


def test_locator_uses_role_link_for_anchors() -> None:
    locator = choose_locator(_raw(tag="a", text="用户协议"), "link")
    assert locator.strategy == "role"
    assert locator.role == "link"


def test_locator_falls_back_to_text_then_css() -> None:
    assert choose_locator(_raw(text="提交"), "unknown").strategy == "text"
    assert choose_locator(_raw(id="phone"), "textbox").strategy == "css"
    assert choose_locator(_raw(id="phone"), "textbox").value == "#phone"


def test_locator_last_resort_is_tag_css() -> None:
    locator = choose_locator({"tag": "DIV"}, "unknown")
    assert locator.strategy == "css"
    assert locator.value == "div"


# ---- 控件命名 ----


def test_choose_name_priority() -> None:
    assert choose_name(_raw(label_text="手机号", placeholder="请输入"), "textbox") == "手机号"
    assert choose_name(_raw(aria_label="验证码", placeholder="请输入"), "textbox") == "验证码"
    assert choose_name(_raw(placeholder="请输入手机号"), "textbox") == "请输入手机号"
    assert choose_name(_raw(text="注册"), "button") == "注册"
    assert choose_name(_raw(id="phone"), "textbox") == "phone"


def test_choose_name_never_empty() -> None:
    assert choose_name({}, "textbox") == "未命名textbox"


# ---- 原始元素 → 控件列表 ----


def test_parse_controls_maps_signup_page() -> None:
    raw_items = [
        {"tag": "input", "type": "tel", "id": "phone", "label_text": "手机号",
         "placeholder": "请输入手机号", "required": True},
        {"tag": "input", "type": "text", "id": "code", "label_text": "验证码", "required": True},
        {"tag": "button", "type": "button", "id": "send-code", "text": "获取验证码"},
        {"tag": "input", "type": "password", "id": "password", "label_text": "密码",
         "required": True},
        {"tag": "input", "type": "checkbox", "id": "agree",
         "label_text": "我已阅读并同意《用户协议》", "required": True},
        {"tag": "button", "type": "submit", "id": "submit", "text": "注册"},
    ]
    controls = parse_controls(raw_items)

    assert len(controls) == 6
    assert all(isinstance(c, Control) for c in controls)
    assert [c.control_type for c in controls] == [
        "textbox", "textbox", "button", "password", "checkbox", "button",
    ]
    assert [c.name for c in controls] == [
        "手机号", "验证码", "获取验证码", "密码", "我已阅读并同意《用户协议》", "注册",
    ]
    assert [c.required for c in controls] == [True, True, False, True, True, False]


def test_parse_controls_skips_unknown_elements() -> None:
    controls = parse_controls([{"tag": "span"}, _raw(label_text="手机号")])
    assert [c.name for c in controls] == ["手机号"]


def test_parse_controls_keeps_select_options() -> None:
    controls = parse_controls(
        [{"tag": "select", "id": "city", "label_text": "城市",
          "options": ["北京", "上海", "广州"]}]
    )
    assert controls[0].control_type == "select"
    assert controls[0].options == ["北京", "上海", "广州"]


def test_parse_controls_records_tag_and_id_in_meta() -> None:
    controls = parse_controls([_raw(id="phone", label_text="手机号")])
    assert controls[0].meta["tag"] == "input"
    assert controls[0].meta["id"] == "phone"


def test_locator_playwright_expression_roundtrip() -> None:
    """生成的定位表达式应可直接用于 Playwright。"""
    control = parse_controls([_raw(label_text="手机号")])[0]
    assert control.locator.to_playwright() == 'get_by_label("手机号")'

    button = parse_controls([{"tag": "button", "id": "ok", "text": "确定"}])[0]
    assert button.locator.to_playwright() == 'get_by_role("button", name="确定")'


def test_page_snapshot_control_count() -> None:
    snapshot = PageSnapshot(url="file:///x.html", controls=parse_controls([_raw(id="a")]))
    assert snapshot.control_count == 1


def test_locator_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError):
        Locator(strategy="magic", value="x")
