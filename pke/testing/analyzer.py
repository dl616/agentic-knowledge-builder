"""Analyzer（分析器）：把瞬时快照提炼成可复用的 PageModel（页面对象模型）。

为什么要这一层？
    PageSnapshot（页面快照）是「当时那一刻的原始素材」——控件可能有噪声、
    没有语义、没有组织关系，直接拿去生成用例会得到一堆零散的点击步骤。
    Analyzer 做三件事，把它变成「人能读懂、能跨版本复用」的资产：

    1. **去噪**：剔掉装饰元素、重复项、识别不出来的空壳控件。
    2. **定性**：判断这个页面是干什么的（注册 / 登录 / 搜索 / 下单），
       页面用途决定了后面套用哪套测试模式（表单校验、权限、异常流程……）。
    3. **组织**：把零散控件组合成业务动作（如「提交注册」= 填 4 项 + 勾选协议 + 点按钮），
       用例以动作为单位组织，才读得懂、改得动。

为什么不用 LLM（大语言模型）做这件事？
    控件识别和动作归类是确定性规则，用规则更稳、更快、可单测、零成本。
    LLM 留给真正需要语义创造力的环节——用例设计（S3）。
    这也让整个探索→建模链路在没有 LLM 的情况下依然能跑通。
"""
from __future__ import annotations

from ..agents.base import Agent, AgentMessage
from .schemas import (
    ACTION_TYPES,
    BusinessAction,
    Control,
    Locator,
    PageModel,
    PageSnapshot,
)

# 页面用途关键词表：(用途, 关键词)
# 命中越多得分越高，同分时取先出现的（表里顺序即优先级）
PURPOSE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("注册", ("注册", "signup", "sign-up", "sign_up", "register", "join", "创建账号")),
    ("登录", ("登录", "login", "log-in", "log_in", "signin", "sign-in", "登陆")),
    ("找回密码", ("找回密码", "忘记密码", "reset password", "forgot", "reset-password")),
    ("搜索", ("搜索", "search", "查询", "query")),
    ("下单", ("下单", "结算", "checkout", "order", "购物车", "cart")),
    ("支付", ("支付", "付款", "pay", "payment")),
    ("个人中心", ("个人中心", "我的", "profile", "account", "设置")),
)

# 按钮文案 → 动作类型（按优先级从上往下匹配）
SUBMIT_KEYWORDS = ("提交", "注册", "登录", "登陆", "确定", "确认", "保存", "下一步", "完成")
QUERY_KEYWORDS = ("获取验证码", "发送验证码", "获取", "发送", "搜索", "查询", "刷新")
RESET_KEYWORDS = ("重置", "清空", "取消", "返回", "上一步")
NAVIGATE_KEYWORDS = ("更多", "详情", "查看", "了解", "帮助", "协议", "条款", "隐私")


def _match_purpose(text: str) -> str:
    """从标题/URL/控件文本里判断页面用途，判断不出返回空串。"""
    haystack = text.lower()
    best_purpose, best_score = "", 0
    for purpose, keywords in PURPOSE_KEYWORDS:
        score = sum(1 for kw in keywords if kw.lower() in haystack)
        if score > best_score:
            best_purpose, best_score = purpose, score
    return best_purpose


def denoise(controls: list[Control]) -> list[Control]:
    """去噪：剔除没价值的控件，并按 (名称, 定位值) 去重。

    三条剔除规则（都是「留着只会污染用例」的情况）：
    1. 类型 unknown 且没有可见文本——识别不出来的空壳。
    2. 没有语义名称——生成用例时无法引用。
    3. 重复项——同一元素被 DOM 与 A11y Tree 各抓到一次是常事。
    """
    cleaned: list[Control] = []
    seen: set[tuple[str, str]] = set()

    for control in controls:
        if control.control_type == "unknown" and not control.text:
            continue
        if not control.name:
            continue
        key = (control.name, control.locator.value or control.locator.name)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(control)
    return cleaned


def _classify_action(button_text: str) -> str:
    """按按钮文案判断它属于哪类业务动作。"""
    for keyword in SUBMIT_KEYWORDS:
        if keyword in button_text:
            return "submit"
    for keyword in RESET_KEYWORDS:
        if keyword in button_text:
            return "reset"
    for keyword in QUERY_KEYWORDS:
        if keyword in button_text:
            return "query"
    for keyword in NAVIGATE_KEYWORDS:
        if keyword in button_text:
            return "navigate"
    return "unknown"


def infer_actions(controls: list[Control]) -> list[BusinessAction]:
    """从控件列表推断业务动作。

    核心规则：**提交类按钮会把页面上的输入控件「收拢」成一个动作**。
    比如注册按钮 → 「提交注册」动作，涉及手机号、验证码、密码、协议勾选。
    这样用例就能写成「执行提交注册，其中手机号为空」，而不是四个零散的 fill 步骤。
    """
    actions: list[BusinessAction] = []
    inputs = [c for c in controls if c.is_input]

    for control in controls:
        if control.control_type == "button":
            action_type = _classify_action(control.text or control.name)
            if action_type == "submit":
                # 提交动作：所有输入框 + 必填勾选框 + 按钮本身
                involved = [c.name for c in inputs]
                involved += [
                    c.name for c in controls if c.control_type == "checkbox" and c.required
                ]
                involved.append(control.name)
                description = "填写表单并提交"
            elif action_type == "query":
                involved = [control.name]
                description = "触发一次查询/获取动作"
            else:
                involved = [control.name]
                description = ""
            actions.append(
                BusinessAction(
                    name=control.text or control.name,
                    action_type=action_type,
                    control_names=involved,
                    description=description,
                )
            )

        elif control.control_type == "checkbox":
            actions.append(
                BusinessAction(
                    name=f"勾选{control.name}",
                    action_type="toggle",
                    control_names=[control.name],
                )
            )

        elif control.control_type == "link":
            actions.append(
                BusinessAction(
                    name=control.text or control.name,
                    action_type="navigate",
                    control_names=[control.name],
                )
            )

    return actions


def build_page_model(snapshot: PageSnapshot) -> PageModel:
    """从页面快照构建页面模型（纯函数，便于单测与复用）。"""
    controls = denoise(snapshot.controls)

    purpose_text = " ".join(
        [snapshot.title, snapshot.url, *[c.name for c in controls], *[c.text for c in controls]]
    )
    purpose = _match_purpose(purpose_text)

    return PageModel(
        url=snapshot.url,
        title=snapshot.title,
        purpose=purpose,
        controls=controls,
        actions=infer_actions(controls),
        meta={
            "source_snapshot_controls": snapshot.control_count,
            "denoised_controls": len(controls),
            "interactions": len(snapshot.interactions),
            "a11y_tree_chars": len(snapshot.a11y_tree),
        },
    )


class AnalyzerAgent(Agent):
    """分析器 Agent：PageSnapshot（页面快照）→ PageModel（页面对象模型）。"""

    name = "analyzer"

    def run(self, msg: AgentMessage) -> AgentMessage:
        snapshot = msg.payload
        if not isinstance(snapshot, PageSnapshot):
            raise TypeError(f"Analyzer 需要 PageSnapshot，收到 {type(snapshot).__name__}")

        model = build_page_model(snapshot)
        return AgentMessage(
            payload=model,
            meta={
                "agent": self.name,
                "purpose": model.purpose,
                "controls": len(model.controls),
                "actions": len(model.actions),
            },
        )


__all__ = [
    "ACTION_TYPES",
    "AnalyzerAgent",
    "BusinessAction",
    "Control",
    "Locator",
    "PageModel",
    "PageSnapshot",
    "build_page_model",
    "denoise",
    "infer_actions",
]
