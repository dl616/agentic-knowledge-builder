"""Explorer 真实浏览器集成测试。

这是与纯函数单测互补的一层：**真的开一个 Chromium 打开页面**。
纯函数单测能保证 parse_controls 的逻辑对，但保证不了「浏览器里跑的 JS 抽取脚本」
是否真的抓得到元素、label 关联是否正确、A11y Tree 是否可读——只有真跑才知道。

验证方法是「已知内容样本断言法」：fixture 页里我亲手放了 6 个控件，
所以「抓到几个、分别是什么类型」是**预先已知**的，不需要肉眼看输出。

标记：需要 Playwright 与浏览器内核，缺失时自动跳过（不阻塞 CI）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pke.agents.base import AgentMessage
from pke.testing.analyzer import AnalyzerAgent
from pke.testing.explorer import ExplorerAgent
from pke.testing.generator import CaseGeneratorAgent
from pke.testing.schemas import PageModel, PageSnapshot

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "signup.html"

pytestmark = pytest.mark.integration


def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401, PLC0415
    except ImportError:
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:  # noqa: BLE001 - 内核未下载时这里会失败
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _playwright_available(),
        reason="Playwright 或 Chromium 内核未安装",
    ),
]


@pytest.fixture(scope="module")
def fixture_url() -> str:
    return FIXTURE.resolve().as_uri()


@pytest.fixture(scope="module")
def snapshot(fixture_url: str) -> PageSnapshot:
    """静态快照（不探测），整个模块复用一次浏览器开销。"""
    return ExplorerAgent(headless=True, probe=False).explore(fixture_url)


# ---- S1 验收：真的抓到了什么 ----


def test_explore_captures_all_six_controls(snapshot: PageSnapshot) -> None:
    """fixture 页已知有 6 个可交互控件，一个都不能少。"""
    assert snapshot.control_count == 6, (
        f"期望 6 个控件，实际 {snapshot.control_count}："
        f"{[(c.name, c.control_type) for c in snapshot.controls]}"
    )


def test_control_types_are_correct(snapshot: PageSnapshot) -> None:
    """控件类型必须归一化正确——这是后续生成用例的唯一依据。

    手机号框 type=tel 要归成 textbox（和 text 一视同仁），
    密码框归 password，勾选框归 checkbox，两个按钮都归 button。
    """
    by_id = {c.meta["id"]: c for c in snapshot.controls}
    assert set(by_id) == {"phone", "code", "send-code", "password", "agree", "submit"}

    assert by_id["phone"].control_type == "textbox"
    assert by_id["code"].control_type == "textbox"
    assert by_id["password"].control_type == "password"
    assert by_id["agree"].control_type == "checkbox"
    assert by_id["send-code"].control_type == "button"
    assert by_id["submit"].control_type == "button"


def test_controls_use_semantic_names(snapshot: PageSnapshot) -> None:
    """控件名应该是「人看得懂的中文」，而不是 id。

    用例里写「在『手机号』输入 xxx」比「在 #phone 输入 xxx」可读得多，
    这也是测试人员愿意审核的前提。
    """
    names = {c.name for c in snapshot.controls}
    assert "手机号" in names
    assert "验证码" in names
    assert "密码" in names
    assert "我已阅读并同意《用户协议》" in names


def test_required_flag_is_captured(snapshot: PageSnapshot) -> None:
    """必填标记要抓到——它是生成「必填项为空」异常用例的依据。"""
    by_id = {c.meta["id"]: c for c in snapshot.controls}
    assert by_id["phone"].required is True
    assert by_id["agree"].required is True


def test_locators_prefer_stable_strategy(snapshot: PageSnapshot) -> None:
    """定位策略优先级：有 label 就用 label，绝不退化到 css。

    这条断言直接守住了「自动化维护成本高」的根因——
    靠 css 定位的脚本，一次改版就全废。
    """
    strategies = {c.locator.strategy for c in snapshot.controls}
    assert "css" not in strategies, f"出现不稳定的 css 定位：{strategies}"
    assert "label" in strategies or "placeholder" in strategies


def test_a11y_tree_is_captured(snapshot: PageSnapshot) -> None:
    """A11y Tree（无障碍树）必须抓到，且包含关键语义节点。

    这是整个方案对抗 UI 改版的核心：DOM 变了树不一定变。
    """
    assert snapshot.a11y_tree.strip(), "A11y Tree 为空"
    # aria_snapshot 的输出形如：- textbox "手机号"
    assert "textbox" in snapshot.a11y_tree
    assert "button" in snapshot.a11y_tree


def test_dom_is_captured_and_sanitized(snapshot: PageSnapshot) -> None:
    """DOM（文档对象模型）要抓，但要去掉 script/style 噪声。"""
    assert snapshot.dom.strip()
    assert "<script" not in snapshot.dom.lower()
    assert "addEventListener" not in snapshot.dom


def test_title_is_captured(snapshot: PageSnapshot) -> None:
    assert snapshot.title.strip(), "页面标题为空"


# ---- 安全边界：提交类按钮绝不碰 ----


def test_probe_never_clicks_submit(fixture_url: str) -> None:
    """安全边界的硬断言：submit（提交）按钮绝对不能被点击。

    真实站点上点提交可能下单、发消息、扣款——探索器必须是只读的观察者。
    fixture 的 submit 如果被点了，会走前端逻辑，但我们的探测根本不该碰它。
    """
    agent = ExplorerAgent(headless=True, probe=True)
    snap = agent.explore(fixture_url)

    targets = {i.target for i in snap.interactions}
    assert "submit" not in targets, f"探测碰了提交按钮：{targets}"
    # 只有 send-code 是 type="button"，属于安全范围
    assert all(t != "注册" for t in targets)


def test_probe_records_effect(fixture_url: str) -> None:
    """探测要记录「操作前后页面发生了什么」——这就是操作轨迹。

    fixture 里点「获取验证码」会把提示区改成「验证码已发送」，
    所以轨迹里必须能观测到这个变化，而不是只记一句「点了一下」。
    """
    agent = ExplorerAgent(headless=True, probe=True)
    snap = agent.explore(fixture_url)

    assert len(snap.interactions) >= 1, "没有记录任何操作轨迹"
    interaction = snap.interactions[0]
    assert interaction.action == "click"
    assert interaction.ok is True, f"探测失败：{interaction.error}"
    assert "验证码已发送" in (interaction.effect or ""), (
        f"未观测到页面反馈：{interaction.effect!r}"
    )


# ---- S1 → S2 串联：探索结果直接喂给 Analyzer ----


def test_snapshot_feeds_analyzer(fixture_url: str) -> None:
    """S1 与 S2 的接缝：探索产物能直接被分析器消费，产出 PageModel。

    这条串起来才叫闭环——任何一侧的契约改动都会在这里暴露。
    走标准 Agent 契约（输入 AgentMessage → 输出 AgentMessage），
    而不是直接调内部函数，这样也顺带验证了编排层能串起来。
    """
    snap = ExplorerAgent(headless=True, probe=False).explore(fixture_url)
    result = AnalyzerAgent().run(AgentMessage(payload=snap))
    model = result.payload
    assert isinstance(model, PageModel)

    assert model.title.strip(), "PageModel 没有标题"
    assert len(model.controls) == 6
    # 注册页的核心动作应该被识别出来
    actions = {a.action_type for a in model.actions}
    assert "submit" in actions, f"未识别出提交动作：{actions}"
    assert "input" in actions or "query" in actions


# ---- S1 → S2 → S3 全链路：真实页面 → 用例 ----


def test_full_pipeline_produces_cases(fixture_url: str) -> None:
    """一条龙：真实浏览器探索 → 建模 → 生成用例。

    这是最能说明「系统真的能跑」的一条断言——
    输入只有一个 URL，输出是 10 条可直接审核的结构化用例。
    """
    snap = ExplorerAgent(headless=True, probe=False).explore(fixture_url)
    model = AnalyzerAgent().run(AgentMessage(payload=snap)).payload
    cases = CaseGeneratorAgent().run(AgentMessage(payload=model)).payload

    assert len(cases) == 10, [c.id for c in cases]

    # 正常流程必须存在且是 P0
    happy = [c for c in cases if c.category == "正常流程"]
    assert len(happy) == 1
    assert happy[0].priority == "P0"

    # 异常校验覆盖手机号/验证码/密码/协议
    titles = " ".join(c.title for c in cases)
    for keyword in ("手机号", "验证码", "密码", "用户协议"):
        assert keyword in titles, f"未覆盖 {keyword}"

    # 每条用例的步骤都要能翻译成 Playwright 操作（不能有空 target）
    for case in cases:
        for step in case.steps:
            if step.action in ("fill", "click", "check", "uncheck"):
                assert step.target, f"{case.id} 的步骤 {step.action} 缺少 target"


def test_generated_cases_are_executable_on_real_page(fixture_url: str) -> None:
    """生成的用例在真实页面上真的能跑——这是「不是纸上谈兵」的硬证据。

    只跑正常流程一条：按用例步骤填入合法值、勾选协议、点注册，
    断言页面真的出现「注册成功」。
    """
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    snap = ExplorerAgent(headless=True, probe=False).explore(fixture_url)
    model = AnalyzerAgent().run(AgentMessage(payload=snap)).payload
    cases = CaseGeneratorAgent().run(AgentMessage(payload=model)).payload
    happy = next(c for c in cases if c.category == "正常流程")

    locator_by_name = {c.name: c.locator for c in model.controls}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(fixture_url)

        for step in happy.steps:
            if step.action == "fill":
                page.get_by_label(step.target).fill(step.value)
            elif step.action == "check":
                page.get_by_label(step.target).check()
            elif step.action == "click":
                page.get_by_role("button", name=step.target).click()

        page.wait_for_timeout(300)
        body_text = page.inner_text("body")
        browser.close()

    assert "注册成功" in body_text, f"用例未跑通，页面文本：{body_text[:200]}"
    assert locator_by_name, "控件定位器映射不应为空"
