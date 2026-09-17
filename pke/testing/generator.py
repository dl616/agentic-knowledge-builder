"""CaseGenerator（用例生成器）：PageModel（页面模型）→ 结构化测试用例。

设计上有一条硬原则：**没有 LLM 也要能跑出可用用例。**

LLM 接入卡过很久（knot 网关地址没打通），如果生成器强依赖它，整条线就瘫了。
所以这里把生成逻辑做成两层：

    规则层（必须）：按控件语义套测试模式——必填项为空、格式非法、边界值、协议未勾选。
                   这部分是**测试领域知识的代码化**，稳定、可测、零成本。
    LLM 层（可选）：有 LLM 时追加「规则想不到的业务用例」——比如「同一手机号重复注册」
                   「验证码过期」这类需要理解业务才能想到的场景。

两层产出的用例都打上 source 标记（rule / llm / history），
出问题时能立刻定位是哪条路径的锅，也方便后续评估「LLM 到底加了多少价值」。

测试模式（TestPattern）是这套东西的核心资产：
    它把资深测试人员的经验固化成代码——「手机号框要测格式」「密码框要测强度」「必填项要测为空」。
    新增一种控件语义，只要往语义层加一条规则，全项目所有页面立刻生效。
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from ..agents.base import Agent, AgentMessage
from .schemas import Control, PageModel, TestCase, TestStep

# 语义层（semantic_id / 字段规则）为什么要单独一个模块：
#   语义身份不只生成器用——执行器要靠它做「跨版本重绑」，断言要靠它取提示关键词。
#   放在生成器里，执行器就得反向依赖生成器，依赖方向会乱。
#   抽成独立一层，三个角色共用同一份语义定义。
from .semantics import (
    FieldRule,
    match_field_rule,
    semantic_id,
)
from .semantics import (
    slug as _slug,
)

# 密码最短长度：边界值用例要用（刚好达标 vs 差一位）
_PASSWORD_MIN_LEN = 8

# 提交类按钮的文案关键词——找不到 submit 动作时的兜底识别
_SUBMIT_WORDS = ("提交", "注册", "登录", "确定", "确认", "保存", "下单", "支付", "搜索")

# 成功提示的兜底文案：按页面用途推断
_SUCCESS_HINTS = {
    "注册": "注册成功",
    "登录": "登录成功",
    "搜索": "搜索结果",
    "下单": "下单成功",
    "支付": "支付成功",
}


def find_submit_control(model: PageModel) -> Control | None:
    """找出提交按钮。

    优先用 Analyzer 识别出的 submit（提交）动作，那是语义级判断；
    找不到再按文案关键词兜底，最后退化为「最后一个按钮」。
    """
    for action in model.actions:
        if action.action_type != "submit":
            continue
        candidates = [model.get_control(name) for name in action.control_names]
        clickable = [c for c in candidates if c is not None and c.is_clickable]
        # 提交动作往往涉及多个控件（输入框 + 勾选框 + 按钮），
        # 但按钮才是「触发提交」的那一个，必须优先挑出来——
        # 否则会误把同样可点击的协议勾选框当成提交按钮。
        for control in clickable:
            if control.control_type == "button":
                return control
        if clickable:
            return clickable[-1]

    for control in model.clickable_controls:
        if control.control_type != "button":
            continue
        if any(word in control.name or word in control.text for word in _SUBMIT_WORDS):
            return control

    buttons = [c for c in model.clickable_controls if c.control_type == "button"]
    return buttons[-1] if buttons else None


def _success_hint(model: PageModel) -> str:
    """推断成功提示文案——执行阶段用它做断言。"""
    for purpose, hint in _SUCCESS_HINTS.items():
        if purpose in (model.purpose or ""):
            return hint
    return "成功"


# ---- 用例组装的公共片段 ----


def _fill_steps(model: PageModel, *, skip: str | None = None) -> list[TestStep]:
    """生成「把所有输入框填上合法值」的步骤。

    skip: 要跳过的控件名（测「必填项为空」时用）。

    每步都带上 semantic_id（语义槽位）：页面改版后字面名变了，
    执行器要靠它把历史用例重绑到新控件上（见 executor.rebind_case）。
    """
    steps: list[TestStep] = []
    for control in model.input_controls:
        if control.name == skip:
            continue
        rule = match_field_rule(control)
        value = rule.valid if rule else "测试内容"
        steps.append(
            TestStep(
                action="fill",
                target=control.name,
                value=value,
                semantic_id=semantic_id(control),
            )
        )
    return steps


def _check_steps(model: PageModel, *, skip: str | None = None) -> list[TestStep]:
    """生成「勾选所有勾选框」的步骤（协议勾选之类）。"""
    return [
        TestStep(action="check", target=c.name, semantic_id=semantic_id(c))
        for c in model.controls
        if c.control_type == "checkbox" and c.name != skip
    ]


def _submit_step(model: PageModel) -> TestStep | None:
    control = find_submit_control(model)
    if control is None:
        return None
    return TestStep(action="click", target=control.name, semantic_id=semantic_id(control))


# ---- 五类测试模式 ----


def _case_happy_path(model: PageModel) -> TestCase:
    """正常流程：全填合法值 + 勾选 + 提交 → 成功。"""
    steps = [TestStep(action="goto", target=model.url, value=model.url)]
    steps += _fill_steps(model)
    steps += _check_steps(model)
    submit = _submit_step(model)
    if submit:
        steps.append(submit)
    hint = _success_hint(model)
    steps.append(TestStep(action="assert_text", value=hint))

    return TestCase(
        id=f"TC-{_slug(model.purpose or 'page')}-happy",
        title=f"正常流程：{model.purpose or '页面'}全部填写合法值后提交成功",
        priority="P0",
        category="正常流程",
        steps=steps,
        expected=f"提交成功，页面出现「{hint}」提示",
        source="rule",
        tags=["happy-path", model.purpose or "unknown"],
    )


def _cases_missing_required(model: PageModel) -> list[TestCase]:
    """必填项为空：每个必填输入各出一条（这是最经典的异常场景）。"""
    cases: list[TestCase] = []
    for control in model.input_controls:
        if not control.required:
            continue
        steps = [TestStep(action="goto", target=model.url, value=model.url)]
        steps += _fill_steps(model, skip=control.name)
        steps += _check_steps(model)
        submit = _submit_step(model)
        if submit:
            steps.append(submit)
        # 拦截类断言：断言「没出现成功提示」，而不是「出现了某句错误提示」。
        # 理由见 schemas.STEP_ACTIONS 里 assert_not_text 的注释——
        # 原生 required 校验不输出任何提示，断言错误文案在改版页上必挂。
        steps.append(
            TestStep(action="assert_not_text", value=_success_hint(model))
        )

        cases.append(
            TestCase(
                id=f"TC-{semantic_id(control)}-required-empty",
                title=f"异常校验：「{control.name}」必填但留空时提交",
                priority="P1",
                category="异常校验",
                steps=steps,
                expected=f"提交被拦截，提示与「{control.name}」相关（如「请输入{control.name}」）",
                source="rule",
                tags=["required", "negative"],
            )
        )
    return cases


def _cases_format_invalid(model: PageModel) -> list[TestCase]:
    """格式非法：手机号填 5 位、密码填 123、验证码填 3 位……"""
    cases: list[TestCase] = []
    for control in model.input_controls:
        rule = match_field_rule(control)
        if rule is None:
            continue
        steps = [TestStep(action="goto", target=model.url, value=model.url)]
        steps += _fill_steps(model, skip=control.name)
        steps.append(
            TestStep(
                action="fill",
                target=control.name,
                value=rule.invalid,
                semantic_id=semantic_id(control),
            )
        )
        steps += _check_steps(model)
        submit = _submit_step(model)
        if submit:
            steps.append(submit)
        # 拦截类断言：断言「没出现成功提示」，而不是「出现了某句错误提示」。
        # 理由见 schemas.STEP_ACTIONS 里 assert_not_text 的注释——
        # 原生 required 校验不输出任何提示，断言错误文案在改版页上必挂。
        steps.append(
            TestStep(action="assert_not_text", value=_success_hint(model))
        )

        cases.append(
            TestCase(
                id=f"TC-{semantic_id(control)}-format-invalid",
                title=f"异常校验：「{control.name}」填入非法值（{rule.constraint}）",
                priority="P1",
                category="异常校验",
                steps=steps,
                expected=f"提交被拦截，提示「{rule.invalid_reason}」",
                source="rule",
                tags=["format", "negative", rule.key],
            )
        )
    return cases


def _cases_boundary(model: PageModel) -> list[TestCase]:
    """边界值：密码刚好 8 位（应通过）vs 7 位（应拦截）。

    边界值是最能体现「测试专业性」的一类——新手测「密码 123 不行」，
    老手测「7 位不行、8 位行」。
    """
    cases: list[TestCase] = []
    password_fields = [
        c
        for c in model.input_controls
        if (rule := match_field_rule(c)) is not None and rule.key == "password"
    ]
    for control in password_fields:
        for length, should_pass in ((_PASSWORD_MIN_LEN, True), (_PASSWORD_MIN_LEN - 1, False)):
            value = "A1b2C3d4"[:length]
            steps = [TestStep(action="goto", target=model.url, value=model.url)]
            steps += _fill_steps(model, skip=control.name)
            steps.append(
                TestStep(
                    action="fill",
                    target=control.name,
                    value=value,
                    semantic_id=semantic_id(control),
                )
            )
            steps += _check_steps(model)
            submit = _submit_step(model)
            if submit:
                steps.append(submit)

            hint = _success_hint(model)
            if should_pass:
                steps.append(TestStep(action="assert_text", value=hint))
                expected = f"提交成功（{length} 位刚好达标），页面出现「{hint}」"
            else:
                # 拦截类断言：断言「没出现成功提示」，而不是「出现了某句错误提示」。
                # 理由见 schemas.STEP_ACTIONS 里 assert_not_text 的注释。
                steps.append(TestStep(action="assert_not_text", value=hint))
                expected = f"提交被拦截（{length} 位低于最短 {_PASSWORD_MIN_LEN} 位）"

            cases.append(
                TestCase(
                    id=f"TC-{semantic_id(control)}-boundary-{length}",
                    title=(
                        f"边界值：「{control.name}」长度 {length} 位"
                        f"（最短 {_PASSWORD_MIN_LEN} 位）"
                    ),
                    priority="P2",
                    category="边界值",
                    steps=steps,
                    expected=expected,
                    source="rule",
                    tags=["boundary", "password"],
                )
            )
    return cases


def _cases_unchecked_agreement(model: PageModel) -> list[TestCase]:
    """协议未勾选：必填勾选框不勾就提交。"""
    cases: list[TestCase] = []
    for control in model.controls:
        if control.control_type != "checkbox" or not control.required:
            continue
        steps = [TestStep(action="goto", target=model.url, value=model.url)]
        steps += _fill_steps(model)
        steps += _check_steps(model, skip=control.name)
        submit = _submit_step(model)
        if submit:
            steps.append(submit)
        # 断言关键词：协议类勾选框通常提示「请先阅读并同意用户协议」，
        # 所以优先断言「同意」；否则退回控件名前 4 个字（避免整句过长匹配不上）。
        # 拦截类断言：断言「没出现成功提示」，而不是「出现了某句错误提示」。
        # 理由见 schemas.STEP_ACTIONS 里 assert_not_text 的注释——
        # 原生 required 校验不输出任何提示，断言错误文案在改版页上必挂。
        steps.append(
            TestStep(action="assert_not_text", value=_success_hint(model))
        )

        cases.append(
            TestCase(
                id=f"TC-{semantic_id(control)}-unchecked",
                title=f"异常校验：未勾选「{control.name}」时提交",
                priority="P1",
                category="异常校验",
                steps=steps,
                expected="提交被拦截，提示需要先同意协议",
                source="rule",
                tags=["agreement", "negative"],
            )
        )
    return cases


# ---- 生成入口 ----


def generate_cases(
    model: PageModel,
    *,
    history: list[TestCase] | None = None,
) -> list[TestCase]:
    """规则层生成：把五类测试模式套到页面上。

    history : 历史用例（S5 会从知识库召回）。命中同 ID 的直接用历史版本，
              这样「上一版审核过的用例」不会被重新生成覆盖掉——
              测试人员对用例的修改是有价值的，不能每次跑都丢。
    """
    cases: list[TestCase] = [_case_happy_path(model)]
    cases += _cases_missing_required(model)
    cases += _cases_format_invalid(model)
    cases += _cases_boundary(model)
    cases += _cases_unchecked_agreement(model)

    if history:
        by_id = {c.id: c for c in history}
        merged: list[TestCase] = []
        for case in cases:
            old = by_id.get(case.id)
            # 命中历史：用上轮审核过的版本，并标记为 history 来源
            merged.append(replace(old, source="history") if old is not None else case)
        cases = merged

    return cases


# ---- LLM 增强层（可选） ----

_LLM_SYSTEM = """你是一名资深测试工程师，擅长从页面模型推导业务测试用例。

只输出 JSON，格式：
{"cases": [{"title": "...", "priority": "P0|P1|P2", "category": "正常流程|异常校验|边界值|安全",
            "steps": [{"action": "fill|click|check|uncheck|assert_text",
                       "target": "...", "value": "..."}],
            "expected": "..."}]}

要求：
1. 只补充规则模板想不到的**业务场景**（如重复注册、验证码过期、并发提交、弱密码、XSS 注入）。
2. 不要重复已有用例。
3. target 必须是给定页面里真实存在的控件名。
4. 控制在 5 条以内，宁缺毋滥。"""


def _llm_enhance(model: PageModel, llm: Any, existing: list[TestCase]) -> list[TestCase]:
    """调用 LLM 补充业务场景用例。失败时静默返回空列表——绝不拖垮主流程。

    为什么要静默：LLM 是增强项，不是必需品。它挂了最多少几条用例，
    不能让「生成用例」这个核心动作整体失败。
    """
    payload = {
        "page": {"url": model.url, "title": model.title, "purpose": model.purpose},
        "controls": [
            {"name": c.name, "type": c.control_type, "required": c.required}
            for c in model.controls
        ],
        "existing_titles": [c.title for c in existing],
    }
    try:
        raw = llm.complete(
            f"页面模型如下，请补充业务测试用例：\n{json.dumps(payload, ensure_ascii=False)}",
            system=_LLM_SYSTEM,
            json_mode=True,
        )
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - LLM 不可用时降级为纯规则，这是设计内的
        return []

    cases: list[TestCase] = []
    for i, item in enumerate(data.get("cases", [])[:5]):
        try:
            steps = [
                TestStep(
                    action=str(s.get("action", "click")),
                    target=str(s.get("target", "")),
                    value=str(s.get("value", "")),
                )
                for s in item.get("steps", [])
            ]
            cases.append(
                TestCase(
                    id=f"TC-llm-{_slug(model.purpose or 'page')}-{i + 1:02d}",
                    title=str(item.get("title", "LLM 生成用例")),
                    priority=str(item.get("priority", "P2")),
                    category=str(item.get("category", "异常校验")),
                    steps=steps,
                    expected=str(item.get("expected", "")),
                    source="llm",
                    tags=["llm"],
                )
            )
        except (ValueError, TypeError):
            # 单条解析失败（优先级/分类/动作不合法）就跳过，不影响其余用例
            continue
    return cases


class CaseGeneratorAgent(Agent):
    """用例生成器 Agent：PageModel（页面模型）→ 测试用例列表。

    llm : 可选。传入 LLMClient 则启用业务场景增强；不传则纯规则生成。
    """

    name = "case_generator"

    def __init__(self, *, llm: Any | None = None) -> None:
        self.llm = llm

    def run(self, msg: AgentMessage) -> AgentMessage:
        model = msg.payload
        if not isinstance(model, PageModel):
            raise TypeError(f"CaseGenerator 需要 PageModel，收到 {type(model).__name__}")

        history = None
        raw_history = msg.meta.get("history") if isinstance(msg.meta, dict) else None
        if isinstance(raw_history, list):
            history = [c for c in raw_history if isinstance(c, TestCase)]

        cases = self.generate(model, history=history)

        return AgentMessage(
            payload=cases,
            meta={
                "agent": self.name,
                "cases": len(cases),
                "by_source": {
                    source: sum(1 for c in cases if c.source == source)
                    for source in ("rule", "llm", "history")
                },
                "llm_enabled": self.llm is not None,
            },
        )

    def generate(
        self, model: PageModel, *, history: list[TestCase] | None = None
    ) -> list[TestCase]:
        cases = generate_cases(model, history=history)
        if self.llm is not None:
            cases += _llm_enhance(model, self.llm, cases)
        return cases


__all__ = [
    "CaseGeneratorAgent",
    "FieldRule",
    "find_submit_control",
    "generate_cases",
    "match_field_rule",
]
