"""跨版本复用单测：语义槽位（semantic_id）能不能把历史用例「接」到新页面上。

这是「积累复用」能不能成立的验收点：

    v1 页面：<label>手机号</label>      → 控件名「手机号」
    v2 页面：去掉 label，只留 placeholder → 控件名「请输入手机号」

字面名全变了。如果用例只认字面名，上一版人工审核过的 10 条用例
在这一版一条都用不上，攒的资产每改版清零一次。

语义槽位（phone / code / password / agreement）不变，
所以用例 ID 稳定、步骤能重绑——这两个性质在这里逐条断言。
"""
from __future__ import annotations

from pke.testing.executor import rebind_case, resolve_control
from pke.testing.generator import generate_cases
from pke.testing.schemas import Control, Locator, PageModel, TestStep
from pke.testing.semantics import assert_hint, semantic_id


def _control(
    name: str,
    control_type: str,
    *,
    element_id: str = "",
    required: bool = False,
    placeholder: str = "",
    nearby_text: str = "",
) -> Control:
    return Control(
        name=name,
        control_type=control_type,
        locator=Locator(strategy="label", name=name),
        text=nearby_text or name,
        required=required,
        meta={
            "id": element_id or name,
            "name": element_id or name,
            "placeholder": placeholder,
            "nearby_text": nearby_text,
        },
    )


def _v1_model() -> PageModel:
    """v1：标签 + 输入框（与 tests/fixtures/signup.html 一致）。"""
    return PageModel(
        url="file:///tmp/signup.html",
        title="用户注册",
        purpose="注册",
        controls=[
            _control("手机号", "textbox", element_id="phone", required=True),
            _control("验证码", "textbox", element_id="code", required=True),
            _control("密码", "password", element_id="password", required=True),
            _control(
                "我已阅读并同意《用户协议》",
                "checkbox",
                element_id="agree",
                required=True,
            ),
            _control("注册", "button", element_id="submit"),
        ],
    )


def _v2_model() -> PageModel:
    """v2：改版后去掉 label，控件名退化成 placeholder（与 signup_v2 一致）。"""
    return PageModel(
        url="file:///tmp/signup_v2.html",
        title="用户注册",
        purpose="注册",
        controls=[
            _control(
                "请输入手机号", "textbox",
                element_id="phone", required=True, placeholder="请输入手机号",
            ),
            _control(
                "请输入验证码", "textbox",
                element_id="code", required=True, placeholder="请输入验证码",
            ),
            _control(
                "请设置密码", "password",
                element_id="password", required=True, placeholder="请设置密码",
            ),
            _control(
                "我已阅读并同意《用户协议》", "checkbox",
                element_id="agree", required=True,
                nearby_text="我已阅读并同意《用户协议》",
            ),
            _control("注册", "button", element_id="submit"),
        ],
    )


# ---- 语义槽位：字面名变了，槽位不变 ----


def test_semantic_id_stable_across_relayout():
    v1 = {c.name: semantic_id(c) for c in _v1_model().controls}
    v2 = {c.name: semantic_id(c) for c in _v2_model().controls}

    assert v1["手机号"] == v2["请输入手机号"] == "phone"
    assert v1["验证码"] == v2["请输入验证码"] == "code"
    assert v1["密码"] == v2["请设置密码"] == "password"
    assert v1["我已阅读并同意《用户协议》"] == v2["我已阅读并同意《用户协议》"] == "agreement"


def test_semantic_id_falls_back_to_html_attrs_when_label_gone():
    """改版把 label 和说明文字都删了（只剩 name="on"）时，靠 id 认出协议框。"""
    naked = _control("on", "checkbox", element_id="agree", required=True)
    assert semantic_id(naked) == "agreement"


def test_assert_hint_uses_short_keyword():
    """断言用「手机号」而不是整句「请输入手机号」——错误提示比标签短。"""
    v2 = {c.name: c for c in _v2_model().controls}
    assert assert_hint(v2["请输入手机号"]) == "手机号"
    assert assert_hint(v2["请设置密码"]) == "密码"
    assert assert_hint(v2["我已阅读并同意《用户协议》"]) == "同意"


# ---- 用例 ID：跨版本稳定，人工改过的版本不会被覆盖 ----


def test_case_ids_stable_across_relayout():
    v1_ids = {c.id for c in generate_cases(_v1_model())}
    v2_ids = {c.id for c in generate_cases(_v2_model())}

    assert "TC-phone-required-empty" in v1_ids
    assert "TC-phone-required-empty" in v2_ids
    # 用例 ID 集合完全一致 = 第二轮能按 ID 命中第一轮的资产
    assert v1_ids == v2_ids


# ---- 步骤重绑：历史用例能绑到新页面控件上 ----


def test_rebind_maps_old_targets_to_new_controls():
    v2 = _v2_model()
    case = next(c for c in generate_cases(_v1_model()) if c.id == "TC-phone-required-empty")

    rebound, notes = rebind_case(case, v2)
    targets = [s.target for s in rebound.steps]

    assert "手机号" not in targets          # 旧名字全部换掉
    assert "请输入验证码" in targets        # 绑定到了 v2 的同语义控件
    assert "请输入密码" not in targets
    assert "请设置密码" in targets
    assert notes                            # 重绑要留痕，报告里要能看到
    assert any("code" in n for n in notes)


def test_rebind_keeps_case_identity():
    """重绑只改步骤指向，不动 ID / 标题语义 / 来源——人工审核结论得以延续。"""
    v2 = _v2_model()
    case = next(c for c in generate_cases(_v1_model()) if c.id == "TC-code-format-invalid")

    rebound, _ = rebind_case(case, v2)
    assert rebound.id == case.id
    assert rebound.priority == case.priority
    assert rebound.category == case.category


def test_rebind_noop_when_page_unchanged():
    """页面没变时不该产生任何重绑记录——没变化却报「已重绑」是误报。"""
    model = _v1_model()
    case = generate_cases(model)[0]
    rebound, notes = rebind_case(case, model)
    assert notes == []
    assert [s.target for s in rebound.steps] == [s.target for s in case.steps]


def test_resolve_control_falls_back_to_semantic_slot():
    v2 = _v2_model()
    step = TestStep(action="fill", target="手机号", value="13800138000", semantic_id="phone")
    control, note = resolve_control(v2, step)
    assert control is not None and control.name == "请输入手机号"
    assert "phone" in note


def test_resolve_control_returns_none_when_control_removed():
    """语义槽位也对不上 = 控件真的没了，必须如实报告，不能瞎绑。"""
    v2 = _v2_model()
    step = TestStep(action="fill", target="推荐人", value="tom", semantic_id="referrer")
    control, note = resolve_control(v2, step)
    assert control is None
    assert note == ""
