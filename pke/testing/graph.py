"""测试流水线编排（S6）：把五个角色编排成一条可观测、可断点重跑的流水线。

为什么要有编排层：
    五个角色（Explorer / Analyzer / 知识召回 / CaseGenerator / Executor / FailureAnalyzer）
    单独都能跑，但「谁先谁后、中间状态怎么传、哪一步失败要不要继续」
    这些决策散在调用方（脚本）里，就没法复用、也没法观测。

    散在脚本里的后果很具体：
      · 想加一个「生成完先自检再执行」的节点，得改脚本；
      · 想看「这一轮到底召回了什么」，得在脚本里加 print；
      · 想从「已有 PageModel」直接开始跑，得把脚本前半段注释掉。
    编排层把这三件事变成：加一个节点 / 读 state / 给 state 传初始值。

为什么选 LangGraph：
    它是 StateGraph（状态图）——节点之间靠**共享状态**通信，而不是函数参数层层传递。
    这正好匹配测试流水线的形态：每一步都在往同一份「这次测试的上下文」里加东西
    （页面模型、召回历史、用例、执行结果、归因报告），后面的节点只读它需要的部分。

    另一个实际好处是**可断点重跑**：state 是可序列化的 dict，
    可以把「探索完、还没生成用例」的状态存下来，改天接着跑——
    真实项目里探索一次大页面很贵，不该因为改了个生成规则就重跑。

降级策略（重要）：
    LangGraph 是可选依赖。装不上（内网、无网、版本冲突）时，
    这里退化成**同样的节点顺序线性执行**，功能一致，只是少了图的可视化与检查点。
    这条原则贯穿全项目：**任何外部依赖都不能让主线停工**（LLM 已经验证过一次）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TypedDict, cast

from ..agents.base import AgentMessage
from .analyzer import AnalyzerAgent
from .executor import CaseExecutor
from .explorer import ExplorerAgent
from .failure import FailureAnalyzerAgent, summarize
from .generator import CaseGeneratorAgent
from .knowledge import TestKnowledgeBase
from .schemas import CaseResult, FailureReport, PageModel, TestCase

__all__ = ["PipelineState", "TestPipeline", "NODE_ORDER"]


# 流水线节点顺序：既是图的边，也是降级时的执行顺序
NODE_ORDER: tuple[str, ...] = (
    "explore",     # 探索：抓页面快照
    "analyze",     # 建模：快照 → PageModel
    "recall",      # 召回：从知识库取可复用的历史用例
    "generate",    # 生成：PageModel + 历史 → 用例集
    "execute",     # 执行：真实浏览器跑一遍
    "attribute",   # 归因：失败/自愈 → 分流报告
    "compile",     # 沉淀：通过的用例 + PageModel 回写知识库
)


class PipelineState(TypedDict, total=False):
    """流水线共享状态——每个节点只读自己需要的键，只写自己产出的键。

    用 TypedDict 而不是 dataclass：LangGraph 的 state 本质是 dict，
    部分更新（节点只回自己那几个键）是它的默认合并语义，
    用 dataclass 反而要自己处理合并。
    """

    url: str                       # 输入：目标页面
    headless: bool                 # 输入：是否无头浏览器
    knowledge_dir: str             # 输入：知识库目录
    execute: bool                  # 输入：是否真的跑浏览器（False 则只生成）

    snapshot: Any                  # explore 产出
    model: PageModel               # analyze 产出
    history: list[TestCase]        # recall 产出（已按语义重绑）
    rebind_notes: list[str]        # recall 产出（重绑留痕）
    cases: list[TestCase]          # generate 产出
    results: list[CaseResult]      # execute 产出
    reports: list[FailureReport]   # attribute 产出
    stored: dict[str, int]         # compile 产出（沉淀统计）

    errors: list[str]              # 任意节点失败时记录，不中断流程


@dataclass
class TestPipeline:
    """测试流水线：对外只有一个 run(url) 动作。

    与自研 Orchestrator 的分工：
        Orchestrator 管的是**知识层**流水线（摄取 → 质检 → 路由 → 索引 → 编译）；
        这里管的是**测试域**流水线（探索 → 建模 → 召回 → 生成 → 执行 → 归因 → 沉淀）。
        两条流水线在「沉淀」这一步交汇：测试资产通过知识层的 Compile/RAG 入库。
    """

    __test__: ClassVar[bool] = False  # 类名以 Test 开头，别让 pytest 当成测试类收集

    knowledge_dir: Path
    headless: bool = True
    llm: Any | None = None
    kb: TestKnowledgeBase = field(init=False)

    def __post_init__(self) -> None:
        self.kb = TestKnowledgeBase(wiki_dir=self.knowledge_dir)

    # ---- 节点实现：每个节点都是 (state) -> 部分 state ----
    def _explore(self, state: PipelineState) -> dict[str, Any]:
        snapshot = ExplorerAgent(headless=state.get("headless", self.headless)).explore(
            state["url"]
        )
        return {"snapshot": snapshot}

    def _analyze(self, state: PipelineState) -> dict[str, Any]:
        model = AnalyzerAgent().run(AgentMessage(payload=state["snapshot"])).payload
        return {"model": model}

    def _recall(self, state: PipelineState) -> dict[str, Any]:
        history = self.kb.history_cases(state["model"])
        return {"history": history, "rebind_notes": list(self.kb.rebind_notes)}

    def _generate(self, state: PipelineState) -> dict[str, Any]:
        cases = CaseGeneratorAgent(llm=state.get("llm", self.llm)).run(
            AgentMessage(payload=state["model"], meta={"history": state.get("history") or []})
        ).payload
        return {"cases": cases}

    def _execute(self, state: PipelineState) -> dict[str, Any]:
        if not state.get("execute", True):
            return {"results": []}
        results = CaseExecutor(headless=state.get("headless", self.headless)).run(
            state["cases"], state["model"], url_override=state.get("url")
        )
        return {"results": results}

    def _attribute(self, state: PipelineState) -> dict[str, Any]:
        results = state.get("results") or []
        if not results:
            return {"reports": []}
        reports = FailureAnalyzerAgent().run(AgentMessage(payload=results)).payload
        return {"reports": reports}

    def _compile(self, state: PipelineState) -> dict[str, Any]:
        results = state.get("results") or []
        if not results:
            return {"stored": {}}
        stored = self.kb.store_run_result(state["model"], state["cases"], results)
        return {"stored": stored}

    _NODES = {
        "explore": _explore,
        "analyze": _analyze,
        "recall": _recall,
        "generate": _generate,
        "execute": _execute,
        "attribute": _attribute,
        "compile": _compile,
    }

    # ---- 两种执行方式：有 LangGraph 走图，没有就线性跑 ----
    def run(self, url: str, *, execute: bool = True, headless: bool | None = None) -> PipelineState:
        """跑完整条流水线，返回最终 state（含所有中间产物，可观测）。"""
        state: PipelineState = {
            "url": url,
            "headless": self.headless if headless is None else headless,
            "knowledge_dir": str(self.knowledge_dir),
            "execute": execute,
            "errors": [],
        }

        graph = _build_graph(self) if _langgraph_available() else None
        if graph is not None:
            # graph.invoke 的返回类型是 dict[Any, Any]（LangGraph 侧无法静态推断），
            # 这里明确收成 PipelineState：调用方拿到的就是完整终态。
            return cast("PipelineState", dict(graph.invoke(state)))

        return self._run_linear(state)

    def _run_linear(self, state: PipelineState) -> PipelineState:
        """降级执行：按 NODE_ORDER 顺序跑节点，节点报错记进 state 不中断。"""
        for name in NODE_ORDER:
            try:
                patch = self._NODES[name](self, state)
                # 节点只回自己产出的那几个键，静态类型是 dict[str, Any]，
                # 合并进 state 时显式收成 PipelineState（TypedDict 的 update 只吃具体类型）。
                state.update(cast("PipelineState", patch))
            except Exception as exc:  # noqa: BLE001 - 编排层要收集错误而不是抛出
                state.setdefault("errors", []).append(f"{name}: {exc}")
                # 前置节点失败时，后续节点没有输入，直接收尾
                break
        return state


def _langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
    except ImportError:
        return False
    return True


def _build_graph(pipeline: TestPipeline) -> Any:
    """组装 LangGraph StateGraph。

    图的结构是线性的，但**每个节点失败都不中断**——
    测试流水线要的是「跑完能拿到一份完整报告」，
    而不是「第一步挂了就啥也没有」。所以错误记进 state.errors，继续往下走。
    """
    from langgraph.graph import END, StateGraph  # noqa: PLC0415

    graph = StateGraph(PipelineState)

    def make_node(name: str):
        def node(state: PipelineState) -> dict[str, Any]:
            try:
                return pipeline._NODES[name](pipeline, state)  # noqa: SLF001
            except Exception as exc:  # noqa: BLE001
                return {"errors": [f"{name}: {exc}"]}

        return node

    for name in NODE_ORDER:
        graph.add_node(name, make_node(name))

    for src, dst in zip(NODE_ORDER, NODE_ORDER[1:], strict=False):
        graph.add_edge(src, dst)
    graph.add_edge(NODE_ORDER[-1], END)
    graph.set_entry_point(NODE_ORDER[0])

    return graph.compile()


def report(state: PipelineState) -> str:
    """把流水线终态渲染成一份人能直接看的报告（测试人员真正要的产出）。"""
    lines: list[str] = []
    model = state.get("model")
    cases = state.get("cases") or []
    results = state.get("results") or []
    reports = state.get("reports") or []

    lines.append(f"页面：{state.get('url', '')}")
    if model is not None:
        lines.append(f"页面模型：{model.title}（{len(model.controls)} 个控件）")

    history = state.get("history") or []
    if history:
        lines.append(f"复用历史用例：{len(history)} 条")
        for note in (state.get("rebind_notes") or [])[:5]:
            lines.append(f"  · 重绑：{note}")

    lines.append(f"用例总数：{len(cases)}")
    if results:
        passed = sum(1 for r in results if r.ok)
        lines.append(f"执行结果：{passed}/{len(results)} 通过")

    needs_human = [r for r in reports if r.needs_human]
    if needs_human:
        lines.append(f"需要人工确认：{len(needs_human)} 条（疑似业务变更）")
    if reports:
        lines.append(summarize(reports))

    if state.get("errors"):
        lines.append("流水线异常：" + "；".join(state["errors"]))

    return "\n".join(lines)
