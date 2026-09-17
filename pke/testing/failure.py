"""FailureAnalyzer（失败归因器）：判断测试「为什么挂」。

这是整个系统里**最体现测试专业性**的一环。

传统自动化最让人崩溃的不是失败，是**失败的噪音**：
改了个 class 名，80 条用例全红；查半天发现功能好好的，只是选择器过期了。
久而久之没人看测试报告了——这才是自动化测试真正的死因。

所以这里把失败分成四类，各自走向不同的处理路径：

    ┌──────────────┬────────────────────┬──────────┬────────────┐
    │ 类型         │ 判定依据           │ 找人？   │ 更新资产？ │
    ├──────────────┼────────────────────┼──────────┼────────────┤
    │ 元素失效     │ 定位器找不到元素   │ 否（自愈）│ 是         │
    │ 元素失效(愈) │ 备选策略跑通了     │ 否       │ 是（改稳的）│
    │ 业务变更     │ 操作都成、预期不对 │ **是**   │ 是         │
    │ 环境错误     │ 网络/崩溃/超时     │ 否（重跑）│ 否         │
    └──────────────┴────────────────────┴──────────┴────────────┘

判定顺序很重要：**先看有没有自愈，再看是不是环境问题，最后才判业务变更。**
因为「业务变更」是要惊动人的判断，必须放在最后、且证据充分时才成立。
"""
from __future__ import annotations

import re

from ..agents.base import Agent, AgentMessage
from .schemas import CaseResult, FailureReport

# 定位类错误的特征（Playwright 报错文本里的关键词）
_LOCATOR_ERROR_PATTERNS = (
    "waiting for locator",
    "waiting for get_by",
    "no element",
    "could not find",
    "not found",
    "strict mode violation",
    "resolved to",
    "element is not visible",
    "element is not attached",
    "timeout .* exceeded",
)

# 环境类错误的特征
_ENVIRONMENT_PATTERNS = (
    "net::err",
    "navigation failed",
    "target closed",
    "browser has been closed",
    "crashed",
    "connection refused",
    "name not resolved",
    "ssl",
    "proxy",
)

_LOCATOR_RE = re.compile("|".join(_LOCATOR_ERROR_PATTERNS), re.IGNORECASE)
_ENVIRONMENT_RE = re.compile("|".join(_ENVIRONMENT_PATTERNS), re.IGNORECASE)


def looks_like_locator_error(message: str) -> bool:
    """判断报错是否源于「定位不到元素」（纯函数，可单测）。"""
    return bool(_LOCATOR_RE.search(message))


def looks_like_environment_error(message: str) -> bool:
    """判断报错是否源于环境（网络、浏览器崩溃等）。"""
    return bool(_ENVIRONMENT_RE.search(message))


def classify(result: CaseResult) -> FailureReport:
    """对一条执行结果做归因（纯函数，核心逻辑都在这里，便于单测）。"""
    # 通过的用例里，可能仍有步骤是靠备选策略跑通的——那也是「元素失效」的信号
    if result.ok:
        healed = result.healed_steps
        if healed:
            detail = "；".join(
                f"「{s.target}」从 {s.strategy_expected} 降级到 {s.strategy_used}"
                for s in healed
            )
            return FailureReport(
                case_id=result.case_id,
                kind="element_healed",
                evidence=f"{len(healed)} 个步骤靠备选定位策略才跑通：{detail}",
                suggestion="把 PageModel 中这些控件的定位器更新为实际生效的策略，下轮不再试错",
                needs_human=False,
                should_update_knowledge=True,
                steps=healed,
            )
        # 用例通过且没有步骤降级，属于「无异常」，不是失败
        return FailureReport(
            case_id=result.case_id,
            kind="unknown",
            evidence="用例通过，无需归因",
            suggestion="",
            needs_human=False,
            should_update_knowledge=False,
        )

    failed = result.failed_step
    if failed is None:
        return FailureReport(
            case_id=result.case_id, kind="unknown",
            evidence=result.error or "未知失败",
            suggestion="人工排查",
            needs_human=True,
        )

    # ① 元素失效：断言步骤不会走到这里，所以能确定是定位问题
    if failed.action in ("fill", "click", "check", "uncheck", "select"):
        if looks_like_environment_error(failed.error):
            return FailureReport(
                case_id=result.case_id,
                kind="environment",
                evidence=f"环境异常：{failed.error[:150]}",
                suggestion="重跑即可；若持续出现，检查网络与浏览器环境",
                needs_human=False,
                should_update_knowledge=False,
                steps=[failed],
            )
        # 控件不存在 or 所有策略都定位不到 —— 都是元素失效
        return FailureReport(
            case_id=result.case_id,
            kind="element_stale",
            evidence=(
                f"步骤 {failed.action}「{failed.target}」定位失败：{failed.error[:150]}"
            ),
            suggestion=(
                "页面结构可能改版。检查该控件是否仍在页面上；"
                "若只是改名/改位置，重新探索一次并更新 PageModel 定位器"
            ),
            needs_human=False,
            should_update_knowledge=True,
            steps=[failed],
        )

    # ② 走到断言这一步说明：元素都在、操作都成功了，只是预期不成立
    if failed.action in ("assert_text", "assert_not_text", "assert_url"):
        return FailureReport(
            case_id=result.case_id,
            kind="business_change",
            evidence=(
                f"操作全部执行成功，但断言不成立：{failed.error[:150]}。"
                f"页面实际内容片段：{result.actual_text[:200]}"
            ),
            suggestion=(
                "这不是脚本问题，是**业务行为变了**。请确认："
                "① 是需求变更（更新用例预期）还是 ② 真的缺陷（提单）"
            ),
            needs_human=True,
            should_update_knowledge=True,
            steps=[failed],
        )

    # ③ 其余（goto / wait 之类）
    if looks_like_environment_error(failed.error):
        return FailureReport(
            case_id=result.case_id,
            kind="environment",
            evidence=f"环境异常：{failed.error[:150]}",
            suggestion="重跑即可",
            needs_human=False,
            should_update_knowledge=False,
            steps=[failed],
        )

    return FailureReport(
        case_id=result.case_id,
        kind="unknown",
        evidence=failed.error[:200],
        suggestion="人工排查",
        needs_human=True,
        should_update_knowledge=False,
        steps=[failed],
    )


class FailureAnalyzerAgent(Agent):
    """失败归因器 Agent：CaseResult（执行结果）→ FailureReport（归因报告）。"""

    name = "failure_analyzer"

    def run(self, msg: AgentMessage) -> AgentMessage:
        payload = msg.payload
        if isinstance(payload, CaseResult):
            results = [payload]
        elif isinstance(payload, list) and all(isinstance(r, CaseResult) for r in payload):
            results = list(payload)
        else:
            raise TypeError(
                f"FailureAnalyzer 需要 CaseResult 或其列表，收到 {type(payload).__name__}"
            )

        reports = [classify(r) for r in results if not r.ok or r.healed_steps]

        return AgentMessage(
            payload=reports,
            meta={
                "agent": self.name,
                "total": len(results),
                "failed": sum(1 for r in results if not r.ok),
                "needs_human": sum(1 for r in reports if r.needs_human),
                "by_kind": {
                    kind: sum(1 for r in reports if r.kind == kind)
                    for kind in ("element_stale", "element_healed", "business_change",
                                 "environment", "unknown")
                },
            },
        )


def summarize(reports: list[FailureReport]) -> str:
    """把归因报告渲染成人能扫一眼就懂的摘要（写进测试报告用）。"""
    if not reports:
        return "全部通过，无需归因。"

    lines: list[str] = []
    human = [r for r in reports if r.needs_human]
    auto = [r for r in reports if not r.needs_human]

    lines.append(f"失败 {len(reports)} 条：需人工确认 {len(human)} 条，可自动处置 {len(auto)} 条")
    lines.append("")
    if human:
        lines.append("【需人工确认】")
        for r in human:
            lines.append(f"  · {r.summary}")
            lines.append(f"    建议：{r.suggestion}")
        lines.append("")
    if auto:
        lines.append("【可自动处置】")
        for r in auto:
            lines.append(f"  · {r.summary}")
            lines.append(f"    处置：{r.suggestion}")
    return "\n".join(lines)


__all__ = [
    "FailureAnalyzerAgent",
    "classify",
    "looks_like_environment_error",
    "looks_like_locator_error",
    "summarize",
]
