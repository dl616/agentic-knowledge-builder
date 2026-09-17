"""执行器：把 TestCase（结构化用例）翻译成 Playwright 操作并跑起来。

关键设计是**多策略自愈**：

    用例里记的定位器是「探索时最好用的那个」，但页面会改版。
    改版后原定位器失效，直接报「测试挂了」是最没价值的输出——
    测试人员还得自己去查是样式改了、文案改了、还是功能真的没了。

    所以这里按稳定性依次尝试备选定位策略：
        label（关联标签）→ placeholder（占位符）→ role（角色）→ text（文本）→ css
    只要有一个能定位到，就跑通，并在 StepResult 里记下「实际用的是哪个策略」。

    这个记录很重要：它会回流到知识库，把 PageModel 的定位器更新成真正稳的那个，
    下次再跑就不用试错了——这就是「资产会自己变好」。
"""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from .schemas import (
    CaseResult,
    Control,
    PageModel,
    StepResult,
    TestCase,
    TestStep,
)
from .semantics import semantic_id

# 备选策略的尝试顺序（越靠前越稳定）
_FALLBACK_ORDER = ("label", "placeholder", "role", "text", "testid", "css")

# 单步超时：短一点，自愈才有试错空间（总共 6 种策略 × 2s = 12s 上限）
_STEP_TIMEOUT_MS = 2_000

# 执行完给页面一点渲染时间，再取文本做断言
_SETTLE_MS = 200


def build_locator(page: Any, control: Control, strategy: str) -> Any:
    """按指定策略构造 Playwright 定位器（纯构造，不校验存在性）。"""
    if strategy == "label":
        return page.get_by_label(control.name, exact=False)
    if strategy == "placeholder":
        return page.get_by_placeholder(str(control.meta.get("placeholder", "")) or control.name)
    if strategy == "role":
        return page.get_by_role(control.aria_role, name=control.name)
    if strategy == "text":
        return page.get_by_text(control.text or control.name, exact=False)
    if strategy == "testid":
        return page.get_by_test_id(control.locator.value)
    # css：优先用 id，没有 id 才退回标签选择器
    element_id = str(control.meta.get("id", "")).strip()
    if element_id:
        return page.locator(f"#{element_id}")
    return page.locator(str(control.meta.get("tag", "")).strip() or "body")


def candidate_strategies(control: Control) -> list[str]:
    """列出该控件可用的定位策略（主策略排第一，其余按稳定性补上）。"""
    primary = control.locator.strategy
    ordered = [primary] + [s for s in _FALLBACK_ORDER if s != primary]
    return ordered


def _apply(locator: Any, step: TestStep) -> None:
    """对一个已定位到的元素执行动作。"""
    if step.action == "fill":
        locator.fill(step.value)
    elif step.action == "click":
        locator.click()
    elif step.action == "check":
        locator.check()
    elif step.action == "uncheck":
        locator.uncheck()
    elif step.action == "select":
        locator.select_option(step.value)


def resolve_control(model: PageModel, step: TestStep) -> tuple[Control | None, str]:
    """把步骤里的控件名解析成当前页面模型里的控件（带回退链 + 说明）。

    三级回退，对应三种真实情况：

    1. 字面名命中   → 页面没变，直接跑。
    2. 语义槽位命中 → 页面改版了（「手机号」→「请输入手机号」），
                      按 semantic_id 重绑到同一个语义控件上。这一步是
                      「人工审核过的历史用例能跨版本继续用」的关键。
    3. 包含关系命中 → 语义槽位缺失（老用例没带）时的兜底模糊匹配。
    """
    if not step.target:
        return None, ""

    exact = model.get_control(step.target)
    if exact is not None:
        return exact, ""

    if step.semantic_id:
        for control in model.controls:
            if semantic_id(control) == step.semantic_id:
                return control, (
                    f"按语义槽位 {step.semantic_id} 重绑："
                    f"「{step.target}」→「{control.name}」"
                )

    for control in model.controls:
        if step.target and (step.target in control.name or control.name in step.target):
            return control, f"模糊重绑：「{step.target}」→「{control.name}」"

    return None, ""


def rebind_case(case: TestCase, model: PageModel) -> tuple[TestCase, list[str]]:
    """把历史用例重绑到当前页面模型上，返回（新用例，重绑说明列表）。

    为什么不在执行时悄悄重绑，而要显式做这一步：
        重绑是**结论**，不是细节。测试人员需要看到
        「这 10 条用例里有 6 条是从上一版复用来的、改了 4 个控件名」，
        才能判断这一版改动的影响面。所以要留痕。
    """
    changes: list[str] = []
    steps: list[TestStep] = []

    for step in case.steps:
        if step.action in ("goto", "assert_text", "assert_not_text", "assert_url", "wait"):
            steps.append(step)
            continue
        control, note = resolve_control(model, step)
        if control is None or control.name == step.target:
            steps.append(step)
            continue
        steps.append(
            TestStep(
                action=step.action,
                target=control.name,
                value=step.value,
                expected=step.expected,
                semantic_id=step.semantic_id or semantic_id(control),
            )
        )
        if note and note not in changes:
            changes.append(note)

    rebound = replace(case, steps=steps)
    return rebound, changes


def run_step(page: Any, step: TestStep, model: PageModel) -> StepResult:
    """执行一个步骤，失败时自动尝试备选定位策略。

    只有「所有策略都定位不到」才算失败——这才是真正的元素失效。
    """
    started = time.monotonic()
    base = StepResult(
        action=step.action,
        target=step.target,
        strategy_expected="",
    )

    # 非控件类步骤（打开页面 / 断言 / 等待）不需要定位
    if step.action in ("goto", "assert_text", "assert_not_text", "assert_url", "wait"):
        try:
            if step.action == "goto":
                page.goto(step.value or step.target)
            elif step.action == "wait":
                page.wait_for_timeout(_SETTLE_MS)
            return StepResult(action=step.action, target=step.target, ok=True,
                              duration_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:  # noqa: BLE001 - 执行层要收集错误而不是抛出
            return StepResult(action=step.action, target=step.target, ok=False,
                              error=str(exc)[:300],
                              duration_ms=int((time.monotonic() - started) * 1000))

    control, note = resolve_control(model, step)
    if control is None:
        return StepResult(
            action=step.action, target=step.target, ok=False,
            error=f"页面模型里找不到控件「{step.target}」，无法执行 {step.action}",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    if note:
        base.note = note

    base.strategy_expected = control.locator.strategy
    last_error = ""
    for strategy in candidate_strategies(control):
        try:
            locator = build_locator(page, control, strategy)
            locator.first.wait_for(state="visible", timeout=_STEP_TIMEOUT_MS)
            _apply(locator.first, step)
            return StepResult(
                action=step.action,
                target=step.target,
                ok=True,
                strategy_used=strategy,
                strategy_expected=control.locator.strategy,
                note=note,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 - 换下一个策略继续试
            last_error = str(exc)[:300]
            continue

    return StepResult(
        action=step.action,
        target=step.target,
        ok=False,
        error=last_error or "所有定位策略均失败",
        strategy_expected=control.locator.strategy,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def run_case(
    page: Any,
    case: TestCase,
    model: PageModel,
    *,
    url_override: str | None = None,
) -> CaseResult:
    """跑完一条用例。

    url_override : 覆盖用例里的 goto 地址。
        用途是「拿 v1 的用例去跑 v2 的页面」——这正是回归测试的真实场景：
        页面改版了，旧用例还能不能用？能用到什么程度？

    断言步骤单独处理：它不定位控件，而是校验页面文本/URL。
    断言失败 ≠ 元素失效——元素都在、操作都成功，只是预期不对，
    那说明**业务变了**，这正是归因（Attribution）要区分的东西。
    """
    started = time.monotonic()
    steps: list[StepResult] = []

    for step in case.steps:
        # 覆盖 goto 地址：让「v1 的用例」能跑在「v2/v3 的页面」上
        if url_override and step.action == "goto":
            step = TestStep(action="goto", target=step.target, value=url_override)

        if step.action in ("assert_text", "assert_not_text"):
            page.wait_for_timeout(_SETTLE_MS)
            body = page.inner_text("body")
            ok = (step.value in body) if step.action == "assert_text" else (step.value not in body)
            reason = (
                f"页面未出现预期文本「{step.value}」"
                if step.action == "assert_text"
                else f"页面出现了不该出现的文本「{step.value}」（提交没被拦截）"
            )
            steps.append(
                StepResult(
                    action=step.action,
                    target=step.target,
                    ok=ok,
                    error="" if ok else reason,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            )
            if not ok:
                break
            continue

        if step.action == "assert_url":
            ok = step.value in page.url
            steps.append(
                StepResult(
                    action=step.action, ok=ok,
                    error="" if ok else f"当前地址 {page.url} 不含「{step.value}」",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            )
            if not ok:
                break
            continue

        result = run_step(page, step, model)
        steps.append(result)
        if not result.ok:
            break

    page.wait_for_timeout(_SETTLE_MS)
    try:
        actual = page.inner_text("body")
    except Exception:  # noqa: BLE001 - 页面已跳转或崩溃时取不到文本
        actual = ""

    failed = next((s for s in steps if not s.ok), None)
    return CaseResult(
        case_id=case.id,
        title=case.title,
        ok=failed is None,
        steps=steps,
        actual_text=actual,
        error=failed.error if failed else "",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


class CaseExecutor:
    """用例执行器：管理浏览器生命周期，批量跑用例。

    每条用例开一个干净的 page（页面上下文），避免相互污染——
    上一条填的值、勾的框不能影响下一条的判断。
    """

    def __init__(self, *, headless: bool = True, settle_ms: int = _SETTLE_MS) -> None:
        self.headless = headless
        self.settle_ms = settle_ms

    @staticmethod
    def _playwright():
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 Playwright。请先执行：pip install playwright && playwright install chromium"
            ) from exc
        return sync_playwright

    def run(
        self,
        cases: list[TestCase],
        model: PageModel,
        *,
        url_override: str | None = None,
    ) -> list[CaseResult]:
        sync_playwright = self._playwright()
        results: list[CaseResult] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                for case in cases:
                    page = browser.new_page()
                    try:
                        results.append(run_case(page, case, model, url_override=url_override))
                    finally:
                        page.close()
            finally:
                browser.close()

        return results


__all__ = [
    "CaseExecutor",
    "build_locator",
    "candidate_strategies",
    "rebind_case",
    "resolve_control",
    "run_case",
    "run_step",
]
