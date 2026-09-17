"""测试资产数据契约。

这一层是「探索 → 建模 → 生成 → 执行 → 沉淀」闭环的共同语言。
和全项目的 schemas.py 一样，遵循三条：

1. **显式声明**：字段类型明确，不靠塞进 dict 里猜。
2. **自带出身**：每个控件都记着自己是怎么被定位到的（strategy 策略），
   否则执行阶段失败时没法判断是「元素失效」还是「业务变更」。
3. **可序列化**：都有 to_dict()，方便沉淀进知识库、写进 Wiki、做 diff。

分层关系：
    PageSnapshot（瞬时快照，一次探索的原始产物）
        → PageModel（稳定模型，可复用资产，沉淀进知识库）
            → TestCase（用例，基于模型 + 历史知识生成）
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

# 契约版本号：字段变更时 +1
SCHEMA_VERSION = 1

# 控件类型（对应 Playwright 的 role 角色，归一化后的结果）
CONTROL_TYPES = (
    "textbox",     # 单行文本输入框
    "password",    # 密码框
    "textarea",    # 多行文本域
    "button",      # 按钮
    "checkbox",    # 勾选框
    "radio",       # 单选框
    "select",      # 下拉选择
    "link",        # 链接
    "file",        # 文件上传
    "unknown",     # 未识别
)

# 用例优先级
PRIORITIES = ("P0", "P1", "P2")  # P0 核心链路 / P1 重要分支 / P2 边缘场景

# 用例分类
CASE_CATEGORIES = (
    "正常流程",   # happy path，主链路走得通
    "异常校验",   # 格式错、必填空、非法值
    "边界值",     # 最小值、最大值、刚好越界
    "安全",       # 越权、注入、敏感信息
)

# 用例来源：决定了「这条用例是人想的、机器套的、还是从历史资产召回的」
CASE_SOURCES = (
    "rule",      # 规则模板生成（无 LLM 也能跑）
    "llm",       # LLM 生成
    "history",   # 历史资产召回复用
)

# 业务动作类型
ACTION_TYPES = (
    "submit",     # 提交（注册、登录、下单）
    "navigate",   # 跳转
    "toggle",     # 开关/勾选
    "input",      # 输入
    "query",      # 查询/搜索
    "reset",      # 重置/清空
    "unknown",
)


@dataclass
class Locator:
    """定位器：记录「怎么找到这个元素」。

    为什么单独建模，而不是直接存一个 CSS 选择器字符串？
    因为失败归因需要知道**当初是靠什么定位的**：
    靠 role（角色）定位的失败 → 多半是页面结构变了（元素失效）；
    靠文本定位的失败 → 可能是文案改了（业务变更）。
    存字符串就丢掉了这层判断依据。

    strategy : 定位策略，见 LOCATOR_STRATEGIES。
    role     : ARIA 角色（role 策略时用）。
    name     : 可访问名称 / 关联 label 文本（role、label 策略时用）。
    value    : 通用值（placeholder 占位符、text 文本、css 选择器、testid 测试标识）。
    """

    strategy: str
    role: str = ""
    name: str = ""
    value: str = ""

    # 定位策略优先级：越靠前越稳定（对 UI 改版越不敏感）
    LOCATOR_STRATEGIES = ("role", "label", "testid", "placeholder", "text", "css")

    def __post_init__(self) -> None:
        if self.strategy not in self.LOCATOR_STRATEGIES:
            raise ValueError(
                f"未知定位策略 {self.strategy!r}，应为 {self.LOCATOR_STRATEGIES} 之一"
            )

    def to_playwright(self) -> str:
        """生成 Playwright 定位表达式（执行阶段直接用）。"""
        if self.strategy == "role":
            arg = f'"{self.role}"'
            if self.name:
                arg += f', name="{self.name}"'
            return f"get_by_role({arg})"
        if self.strategy == "label":
            return f'get_by_label("{self.name or self.value}")'
        if self.strategy == "testid":
            return f'get_by_test_id("{self.value}")'
        if self.strategy == "placeholder":
            return f'get_by_placeholder("{self.value}")'
        if self.strategy == "text":
            return f'get_by_text("{self.value}")'
        return f'locator("{self.value}")'

    @property
    def stability(self) -> int:
        """稳定性评分（越小越稳定），用于失败归因时挑备选定位策略。"""
        return self.LOCATOR_STRATEGIES.index(self.strategy)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 控件类型 → ARIA 角色（无障碍角色）映射
_ROLE_BY_CONTROL_TYPE: dict[str, str] = {
    "textbox": "textbox",
    "password": "textbox",
    "textarea": "textbox",
    "button": "button",
    "link": "link",
    "checkbox": "checkbox",
    "radio": "radio",
    "select": "combobox",
    "file": "button",
}


@dataclass
class Control:
    """页面上的一个可交互控件。

    name         : 语义化名称（如「手机号输入框」），人能看懂，用例里引用它。
    control_type : 归一化后的控件类型，见 CONTROL_TYPES。
    locator      : 定位方式。
    text         : 可见文本（按钮文案、链接文字）。
    required     : 是否必填（从 required / aria-required 推断）。
    options      : 下拉/单选的可选项。
    """

    name: str
    control_type: str
    locator: Locator
    text: str = ""
    required: bool = False
    options: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.control_type not in CONTROL_TYPES:
            raise ValueError(f"未知控件类型 {self.control_type!r}，应为 {CONTROL_TYPES} 之一")

    @property
    def is_input(self) -> bool:
        """是否需要输入内容（生成用例时据此造测试数据）。"""
        return self.control_type in ("textbox", "password", "textarea", "file")

    @property
    def is_clickable(self) -> bool:
        return self.control_type in ("button", "link", "checkbox", "radio")

    @property
    def aria_role(self) -> str:
        """对应的 ARIA 角色（无障碍角色），Playwright 的 get_by_role 需要它。

        放在契约层而不是执行层，是因为「控件类型 → 角色」属于领域知识，
        探索、建模、执行、自愈四处都要用，不能各写一份。
        """
        return _ROLE_BY_CONTROL_TYPE.get(self.control_type, "generic")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Interaction:
    """操作轨迹中的一步：做了什么、页面变成什么样。

    这是 Explorer「主动探索」的证据——只截图不操作，就不知道点了按钮之后会发生什么。
    """

    action: str  # click（点击）/ fill（填写）/ check（勾选）/ select（选择）/ goto（跳转）
    target: str  # 目标控件名
    value: str = ""
    url_before: str = ""
    url_after: str = ""
    effect: str = ""  # 观测到的效果描述（如「出现错误提示：请输入手机号」）
    ok: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageSnapshot:
    """一次页面探索的原始快照。

    这是「瞬时数据」：DOM（文档对象模型）、A11y Tree（无障碍树）、控件列表、操作轨迹。
    它不直接复用——要经 Analyzer 提炼成 PageModel 才成为资产。

    dom        : 精简后的 DOM 文本（原始 HTML 太长且噪声多，只保留结构骨架）。
    a11y_tree  : 无障碍树，比 DOM 稳定——它只描述「用户能看到/能操作的东西」，
                 不包含纯装饰性的 div 嵌套，改样式不会让它失效。
    """

    url: str
    title: str = ""
    dom: str = ""
    a11y_tree: str = ""
    controls: list[Control] = field(default_factory=list)
    interactions: list[Interaction] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def control_count(self) -> int:
        return len(self.controls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "dom": self.dom,
            "a11y_tree": self.a11y_tree,
            "controls": [c.to_dict() for c in self.controls],
            "interactions": [i.to_dict() for i in self.interactions],
            "meta": self.meta,
        }


@dataclass
class BusinessAction:
    """业务动作：控件之上「人能理解的一个操作」。

    例如「提交注册」= 填手机号 + 填验证码 + 填密码 + 勾选协议 + 点注册按钮。
    用例生成时以动作为单位组织，而不是零散的控件点击，这样用例才读得懂。
    """

    name: str
    action_type: str
    control_names: list[str] = field(default_factory=list)
    description: str = ""

    def __post_init__(self) -> None:
        if self.action_type not in ACTION_TYPES:
            raise ValueError(f"未知动作类型 {self.action_type!r}，应为 {ACTION_TYPES} 之一")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageModel:
    """页面对象模型（PageModel）——可复用的测试资产。

    与 PageSnapshot 的区别：快照是一次性的原始数据，模型是提炼后的稳定资产。
    模型会沉淀进知识库（Compile 层），下一个版本做需求 diff 时直接复用。

    purpose  : 页面用途（注册 / 登录 / 搜索 / 下单……），决定套用哪些测试模式。
    controls : 去噪后的控件列表（装饰元素、广告、临时弹窗已被剔除）。
    actions  : 从控件组合推断出的业务动作。
    """

    url: str
    title: str = ""
    purpose: str = ""
    controls: list[Control] = field(default_factory=list)
    actions: list[BusinessAction] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def get_control(self, name: str) -> Control | None:
        """按名称取控件（用例生成时按名字引用控件）。"""
        for control in self.controls:
            if control.name == name:
                return control
        return None

    @property
    def input_controls(self) -> list[Control]:
        return [c for c in self.controls if c.is_input]

    @property
    def clickable_controls(self) -> list[Control]:
        return [c for c in self.controls if c.is_clickable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "purpose": self.purpose,
            "controls": [c.to_dict() for c in self.controls],
            "actions": [a.to_dict() for a in self.actions],
            "meta": self.meta,
            "schema_version": self.schema_version,
        }

    def to_markdown(self) -> str:
        """转成 Markdown——沉淀进 Wiki 知识库的格式（S5 会用）。

        为什么要能转 Markdown：知识层的 Compile 沉淀、RAG 检索、人工查阅
        都基于文本，模型不能只在内存里。
        """
        lines = [
            f"# {self.title or self.url}",
            "",
            f"- URL：{self.url}",
            f"- 页面用途：{self.purpose or '（未识别）'}",
            f"- 控件数：{len(self.controls)}",
            f"- 业务动作数：{len(self.actions)}",
            "",
            "## 控件",
            "",
            "| 名称 | 类型 | 定位方式 | 必填 |",
            "| --- | --- | --- | --- |",
        ]
        for c in self.controls:
            lines.append(
                f"| {c.name} | {c.control_type} | `{c.locator.to_playwright()}` | "
                f"{'是' if c.required else '否'} |"
            )
        if self.actions:
            lines += ["", "## 业务动作", ""]
            for a in self.actions:
                involved = "、".join(a.control_names) or "—"
                lines.append(f"- **{a.name}**（{a.action_type}）：涉及 {involved}")
                if a.description:
                    lines.append(f"  - {a.description}")
        return "\n".join(lines)


# ---- 用例契约 ----

# 步骤动作：与 Playwright 的操作一一对应，执行层可直接翻译
STEP_ACTIONS = (
    "goto",          # 打开页面
    "fill",          # 输入文本
    "click",         # 点击
    "check",         # 勾选
    "uncheck",       # 取消勾选
    "select",        # 下拉选择
    "assert_text",   # 断言页面出现某文本
    # 断言页面**不出现**某文本：拦截类用例（必填为空 / 格式非法）的正确断言方式。
    # 为什么需要：错误提示文案不是每个页面都有——HTML5 原生 required 校验
    # 会直接拦住提交、一句话都不输出。此时断言「出现『手机号』提示」必然失败，
    # 但页面其实是对的（提交确实被拦了）。断言「不出现成功提示」才是稳定表达。
    "assert_not_text",
    "assert_url",    # 断言跳转到某地址
    "wait",          # 等待
)


@dataclass
class TestStep:
    """用例的一个步骤。

    为什么不直接存自然语言（「在手机号框输入 xxx」）？
    因为执行层需要结构化翻译——action + target + value 才能映射成
    Playwright 的 page.fill(locator, value)，自由文本没法可靠执行。
    展示层再把它渲染成人话（见 describe()），两边兼顾。
    """

    # 名字以 Test 开头会让 pytest 误当成测试类来收集，显式关掉
    __test__: ClassVar[bool] = False

    action: str
    target: str = ""      # 控件名（执行时按名字回查定位器）
    value: str = ""
    expected: str = ""    # 本步的局部预期（可空，用例级 expected 才是总预期）

    # 控件的语义槽位（phone / code / password / agreement……），来自 semantics.semantic_id。
    # 为什么需要：页面改版后 target（字面名）会变，但语义槽位不变。
    # 执行时先按 target 找，找不到就按 semantic_id 重绑——
    # 这是「上一版审核过的用例，这一版还能直接跑」的技术前提。
    semantic_id: str = ""

    def __post_init__(self) -> None:
        if self.action not in STEP_ACTIONS:
            raise ValueError(f"未知步骤动作 {self.action!r}，应为 {STEP_ACTIONS} 之一")

    def describe(self) -> str:
        """渲染成测试人员读得懂的一句话。"""
        verb = {
            "goto": "打开页面",
            "fill": "输入",
            "click": "点击",
            "check": "勾选",
            "uncheck": "取消勾选",
            "select": "选择",
            "assert_text": "断言出现文本",
            "assert_not_text": "断言不出现文本",
            "assert_url": "断言跳转到",
            "wait": "等待",
        }[self.action]
        if self.action == "goto":
            return f"打开 {self.value or self.target}"
        if self.action in ("fill", "select"):
            return f"在「{self.target}」{verb}「{self.value}」"
        if self.action in ("check", "uncheck"):
            return f"{verb}「{self.target}」"
        if self.action in ("assert_text", "assert_not_text", "assert_url"):
            return f"{verb}「{self.value}」"
        return f"{verb}「{self.target or self.value}」"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestCase:
    """一条结构化测试用例。

    设计的三个考量：

    1. **可审核**：测试人员的工作变成「看这些用例对不对」，
       所以 steps 要能渲染成人话，expected 要说清预期。
    2. **可执行**：每条步骤都能翻译成 Playwright 操作，不留自由文本。
    3. **可追溯**：source 字段标出这条用例是规则套的、LLM 想的、还是历史召回的。
       出问题时能立刻定位是哪条路径产出的——这对后续调 prompt / 改规则至关重要。
    """

    __test__: ClassVar[bool] = False

    id: str
    title: str
    priority: str = "P1"
    category: str = "正常流程"
    steps: list[TestStep] = field(default_factory=list)
    expected: str = ""
    precondition: str = ""
    source: str = "rule"
    tags: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.priority not in PRIORITIES:
            raise ValueError(f"未知优先级 {self.priority!r}，应为 {PRIORITIES} 之一")
        if self.category not in CASE_CATEGORIES:
            raise ValueError(f"未知分类 {self.category!r}，应为 {CASE_CATEGORIES} 之一")
        if self.source not in CASE_SOURCES:
            raise ValueError(f"未知来源 {self.source!r}，应为 {CASE_SOURCES} 之一")

    def describe(self) -> str:
        """渲染成人读的一句话摘要（审核时一眼扫过用）。"""
        lines = [f"[{self.priority}/{self.category}] {self.title}"]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"  {i}. {step.describe()}")
        lines.append(f"  预期：{self.expected}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "priority": self.priority,
            "category": self.category,
            "steps": [s.to_dict() for s in self.steps],
            "expected": self.expected,
            "precondition": self.precondition,
            "source": self.source,
            "tags": list(self.tags),
            "schema_version": self.schema_version,
        }

    def to_markdown(self) -> str:
        """转成 Markdown——沉淀进知识库、导出给测试人员审核的格式。"""
        lines = [
            f"### {self.id} · {self.title}",
            "",
            f"- 优先级：{self.priority}",
            f"- 分类：{self.category}",
            f"- 来源：{self.source}",
        ]
        if self.precondition:
            lines.append(f"- 前置条件：{self.precondition}")
        lines += ["", "**步骤**", ""]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"{i}. {step.describe()}")
        lines += ["", f"**预期结果**：{self.expected}", ""]
        return "\n".join(lines)


# ---- 执行与失败归因契约 ----

# 失败类型：这是 FailureAnalyzer（失败归因器）的核心分类
FAILURE_KINDS = (
    "element_stale",    # 元素失效：定位器找不到元素了（页面改版，选择器过期）
    "element_healed",   # 元素失效但已自愈：靠备选定位策略跑通了
    "business_change",  # 业务变更：元素都在、操作都成，但预期的结果变了
    "environment",      # 环境错误：网络不通、浏览器崩溃、超时
    "unknown",
)


@dataclass
class StepResult:
    """一个步骤的执行结果。

    strategy_used 是关键：它记下「实际靠哪个定位策略跑通的」。
    当它与用例原本的策略不一致时，说明发生了自愈——
    这个信息要回流到知识库，把 PageModel 的定位器更新成稳的那个。
    """

    __test__: ClassVar[bool] = False

    action: str
    target: str = ""
    ok: bool = True
    error: str = ""
    strategy_used: str = ""
    strategy_expected: str = ""
    duration_ms: int = 0
    # 重绑/自愈的人话说明（「按语义槽位 phone 重绑：手机号 → 请输入手机号」），
    # 直接进报告，让测试人员知道这条用例为什么还能跑。
    note: str = ""

    @property
    def healed(self) -> bool:
        """是否靠备选策略才跑通（自愈）。"""
        return (
            self.ok
            and bool(self.strategy_expected)
            and bool(self.strategy_used)
            and self.strategy_used != self.strategy_expected
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CaseResult:
    """一条用例的执行结果。"""

    __test__: ClassVar[bool] = False

    case_id: str
    title: str
    ok: bool
    steps: list[StepResult] = field(default_factory=list)
    actual_text: str = ""   # 执行结束时的页面文本，归因时的证据
    error: str = ""
    duration_ms: int = 0

    @property
    def healed_steps(self) -> list[StepResult]:
        return [s for s in self.steps if s.healed]

    @property
    def failed_step(self) -> StepResult | None:
        return next((s for s in self.steps if not s.ok), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "ok": self.ok,
            "steps": [s.to_dict() for s in self.steps],
            "actual_text": self.actual_text[:2000],
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class FailureReport:
    """失败报告：归因结论 + 处置建议。

    为什么要单独建模，而不是直接抛个异常字符串？
    因为**不同的失败要走向不同的处理路径**：

        元素失效 → 机器自愈，更新定位器，不需要人
        业务变更 → 报警给人，因为「业务是不是真的该变」只有人能判断
        环境错误 → 重跑就行，不用改任何资产

    needs_human 与 should_update_knowledge 两个布尔值就是分流开关，
    执行层照着它们决定「自愈 / 报警 / 重跑」。
    """

    __test__: ClassVar[bool] = False

    case_id: str
    kind: str
    evidence: str = ""
    suggestion: str = ""
    needs_human: bool = False
    should_update_knowledge: bool = False
    steps: list[StepResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in FAILURE_KINDS:
            raise ValueError(f"未知失败类型 {self.kind!r}，应为 {FAILURE_KINDS} 之一")

    @property
    def summary(self) -> str:
        label = {
            "element_stale": "元素失效（定位器过期）",
            "element_healed": "元素失效（已自愈）",
            "business_change": "业务变更（需人工确认）",
            "environment": "环境错误（可重跑）",
            "unknown": "原因不明",
        }[self.kind]
        return f"[{label}] {self.case_id}：{self.evidence}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "kind": self.kind,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
            "needs_human": self.needs_human,
            "should_update_knowledge": self.should_update_knowledge,
            "steps": [s.to_dict() for s in self.steps],
        }
