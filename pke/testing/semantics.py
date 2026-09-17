"""控件语义层：回答「这个控件到底是谁」。

控件字面名（label / placeholder）会随改版变，语义身份（槽位）不会：

    v1：<label>手机号</label>  → name = "手机号"
    v2：placeholder="请输入手机号" → name = "请输入手机号"

字面名变了，但两者都是同一个「手机号输入框」。
如果用例只认字面名，上一版人工审核过的用例就全部对不上号，
沉淀的资产每改版一次清零一次——「积累复用」直接断在这里。

所以把语义身份单独抽成一层，供三处共用：

    用例 ID      → TC-phone-format-invalid（跨版本稳定，人工改过的用例不会被覆盖）
    步骤绑定     → 历史用例的 target 按语义槽位重绑到新页面控件（跨版本可执行）
    断言关键词   → 断言「手机号」而不是整句「请输入手机号」（提示文案更短更稳）
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import Control

__all__ = [
    "FieldRule",
    "FIELD_RULES",
    "match_field_rule",
    "semantic_id",
    "assert_hint",
    "slug",
]


@dataclass(frozen=True)
class FieldRule:
    """一类输入字段的测试规则。

    key           : 语义槽位（phone / code / password……），跨版本稳定。
    keywords      : 命中关键词（匹配控件名、占位符、id）。
    valid         : 合法样例值（正常流程用）。
    invalid       : 非法样例值（格式校验用例用）。
    invalid_reason: 人话说明为什么非法，写进用例预期里。
    constraint    : 约束描述，写进用例标题，让审核的人一眼看懂测的是什么。
    hint          : 断言关键词。

        hint 为什么不能直接用控件名：错误提示通常比标签短——
        标签是「请输入手机号」，提示是「手机号格式不正确」。
        断言整句必然匹配不上，所以这里存「提示里最可能出现的那个词」。
    """

    key: str
    keywords: tuple[str, ...]
    valid: str
    invalid: str
    invalid_reason: str
    constraint: str
    hint: str


FIELD_RULES: tuple[FieldRule, ...] = (
    FieldRule(
        key="phone",
        keywords=("手机号", "手机", "电话", "phone", "mobile", "tel"),
        valid="13800138000",
        invalid="12345",
        invalid_reason="手机号应为 11 位数字且以 1 开头",
        constraint="11 位手机号格式",
        hint="手机号",
    ),
    FieldRule(
        key="code",
        keywords=("验证码", "校验码", "动态码", "code", "captcha", "otp", "sms"),
        valid="123456",
        invalid="123",
        invalid_reason="验证码位数不足",
        constraint="验证码位数",
        hint="验证码",
    ),
    FieldRule(
        key="password",
        keywords=("密码", "口令", "password", "pwd"),
        valid="Passw0rd2024",
        invalid="123",
        invalid_reason="密码强度不足（长度过短）",
        constraint="密码强度",
        hint="密码",
    ),
    FieldRule(
        key="email",
        keywords=("邮箱", "邮件", "email", "mail"),
        valid="tester@example.com",
        invalid="not-an-email",
        invalid_reason="邮箱格式不正确",
        constraint="邮箱格式",
        hint="邮箱",
    ),
    FieldRule(
        key="idcard",
        keywords=("身份证", "证件号", "idcard", "id_card"),
        valid="11010119900307123X",
        invalid="1234",
        invalid_reason="身份证号位数不正确",
        constraint="身份证号格式",
        hint="身份证",
    ),
)

# 协议类勾选框的语义线索：改版后字面名可能退化成 "on" / 空，只能靠属性救回来
_AGREEMENT_WORDS = ("协议", "条款", "同意", "agreement", "agree", "terms")


def slug(text: str) -> str:
    """把中文/英文混排的文案压成稳定的短 ID（非文字字符统一折叠）。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text.strip().lower())
    return cleaned.strip("-") or "x"


def match_field_rule(control: Control) -> FieldRule | None:
    """判断一个输入控件属于哪类字段（纯函数，可单测）。

    匹配顺序：先按关键词（最准），再按控件类型兜底（密码框一定是密码字段）。
    """
    haystack = " ".join(
        [control.name, control.text, control.locator.value, str(control.meta.get("id", ""))]
    ).lower()

    for rule in FIELD_RULES:
        for keyword in rule.keywords:
            if keyword.lower() in haystack:
                return rule
    # 密码框即使没写「密码」两个字，类型本身就说明了一切
    if control.control_type == "password":
        return next(r for r in FIELD_RULES if r.key == "password")
    return None


def semantic_id(control: Control) -> str:
    """控件的语义槽位标识——用例 ID 与跨版本绑定都用它，而不是控件字面名。

    优先级：

    1. 字段规则命中的槽位（phone / code / password / email / idcard）——最稳。
    2. 协议类勾选框 → agreement（改版后 label 常丢，只能靠 id / name / 相邻文本认）。
    3. 退化：其他勾选框 → checkbox；其余用字面名 slug。
    """
    rule = match_field_rule(control)
    if rule is not None:
        return rule.key

    # 可见文案可能因为改版丢失（去掉 <label> 后控件名会退化成 "on"），
    # 回看 HTML 属性——id / name / placeholder 往往比可见文案更稳定。
    attrs = " ".join(
        str(control.meta.get(key, "")) for key in ("id", "name", "placeholder", "nearby_text")
    )
    haystack = f"{control.name} {control.text} {attrs}"
    if any(w in haystack for w in _AGREEMENT_WORDS):
        return "agreement"
    if control.control_type == "checkbox":
        return "checkbox"
    if control.control_type == "button":
        return f"button-{slug(control.text or control.name)}"
    return slug(control.name)


def assert_hint(control: Control) -> str:
    """断言关键词：错误提示里最可能出现的那个词。

    字段控件用规则的 hint（「手机号」），比字面名「请输入手机号」短且稳；
    协议勾选框固定断言「同意」；其余退回字面名（并截断，避免整句匹配不上）。
    """
    rule = match_field_rule(control)
    if rule is not None:
        return rule.hint
    if semantic_id(control) == "agreement":
        return "同意"
    return control.name[:8]
