"""端到端 demo：给一个 URL，自动探索 → 建模 → 生成用例 → 打印出来给人审核。

用法：
    python scripts/demo_pipeline.py                       # 用内置注册页 fixture
    python scripts/demo_pipeline.py https://example.com   # 指定页面
    python scripts/demo_pipeline.py <url> --execute       # 顺带把正常流程跑一遍
    python scripts/demo_pipeline.py --execute --next-url <v2页面>   # 演示闭环复用
    python scripts/demo_pipeline.py <url> --graph                   # 走 LangGraph 编排层

    # 关键演示：v1 跑完沉淀资产，v2 进来时召回复用
    python scripts/demo_pipeline.py --execute \
        --next-url file:///.../tests/fixtures/signup_v2_relayout.html

这个脚本存在的意义：让「系统真的能跑」这件事一眼可见，
而不是只在测试里断言通过。面试/汇报时直接跑它。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pke.agents.base import AgentMessage  # noqa: E402
from pke.testing.analyzer import AnalyzerAgent  # noqa: E402
from pke.testing.executor import CaseExecutor  # noqa: E402
from pke.testing.explorer import ExplorerAgent  # noqa: E402
from pke.testing.generator import CaseGeneratorAgent  # noqa: E402
from pke.testing.graph import TestPipeline, _langgraph_available, report  # noqa: E402
from pke.testing.knowledge import TestKnowledgeBase  # noqa: E402
from pke.testing.schemas import PageModel, TestCase  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "signup.html"

_BAR = "─" * 68


def _hr(title: str) -> None:
    print(f"\n{_BAR}\n{title}\n{_BAR}")


def main() -> int:
    parser = argparse.ArgumentParser(description="智能测试设计系统 · 端到端 demo")
    parser.add_argument("url", nargs="?", default="", help="目标页面 URL，缺省用内置注册页")
    parser.add_argument("--probe", action="store_true", help="开启主动探测（点击安全按钮）")
    parser.add_argument("--execute", action="store_true", help="把正常流程用例真跑一遍")
    parser.add_argument("--markdown", action="store_true", help="输出 Markdown 格式（便于导出）")
    parser.add_argument("--next-url", default="", help="第二轮页面 URL，演示沉淀后复用的效果")
    parser.add_argument(
        "--graph",
        action="store_true",
        help="走编排层（LangGraph 状态图；未安装则自动降级为线性执行）",
    )
    parser.add_argument(
        "--knowledge-dir",
        default=str(ROOT / ".cache" / "test_wiki"),
        help="测试知识库目录（PageModel 沉淀到 Wiki，用例索引进 RAG）",
    )
    args = parser.parse_args()

    url = args.url or FIXTURE.resolve().as_uri()
    kb = TestKnowledgeBase(Path(args.knowledge_dir))

    if args.graph:
        # 编排层演示：一条命令跑完七个节点，终态 state 直接渲染成报告
        _hr("编排层流水线（LangGraph）")
        engine = "LangGraph 状态图" if _langgraph_available() else "线性降级（未装 langgraph）"
        print(f"   编排引擎：{engine}")
        state = TestPipeline(knowledge_dir=Path(args.knowledge_dir)).run(url)
        print()
        print(report(state))
        return 0


    _round(url, args, kb, round_no=1)

    if args.next_url:
        _hr("⑥ 第二轮：页面改版后重新进场（演示积累复用）")
        _round(args.next_url, args, kb, round_no=2)

    _hr("完成")
    return 0


def _round(url: str, args: argparse.Namespace, kb: TestKnowledgeBase, *, round_no: int) -> None:
    """跑一轮完整流程：探索 → 建模 → 生成 → 执行 → 沉淀。"""
    tag = f"第 {round_no} 轮"

    _hr(f"① Explorer 探索（{tag}）：{url}")
    snap = ExplorerAgent(headless=True, probe=args.probe).explore(url)
    print(f"   标题：{snap.title}")
    print(f"   控件：{snap.control_count} 个")
    print(f"   A11y Tree（无障碍树）：{len(snap.a11y_tree)} 字符")
    for control in snap.controls:
        flag = "必填" if control.required else "  —"
        print(f"     · {control.control_type:<9} {control.name:<24} [{flag}]")
    if snap.interactions:
        print(f"   操作轨迹：{len(snap.interactions)} 条")
        for i in snap.interactions:
            print(f"     · {i.action} {i.target} → {i.effect or '（无明显变化）'}")

    _hr(f"② Analyzer 建模（{tag}）")
    model: PageModel = AnalyzerAgent().run(AgentMessage(payload=snap)).payload
    print(f"   页面用途：{model.purpose or '（未识别）'}")
    print(f"   去噪后控件：{len(model.controls)} 个（原始 {snap.control_count} 个）")
    for action in model.actions:
        involved = "、".join(action.control_names) or "—"
        print(f"     · {action.name}（{action.action_type}）：{involved}")

    # 知识召回：第二轮这里就能拿到第一轮沉淀的资产
    history = kb.history_cases(model)
    recalled = kb.recall_for_model(model)
    if round_no > 1 or recalled:
        _hr(f"③ 知识召回（{tag}）")
        print(f"   知识库现状：{kb.model_count} 个页面模型、{kb.case_count} 条用例、"
              f"{kb.chunk_count} 个知识片段")
        print(f"   召回历史资产：{len(recalled)} 条，可直接复用用例：{len(history)} 条")
        if kb.rebind_notes:
            print(f"   语义重绑 {len(kb.rebind_notes)} 处"
                  f"（改版后控件名变了，按语义槽位重新对上）：")
            for note in kb.rebind_notes[:6]:
                print(f"     · {note}")

    _hr(f"④ CaseGenerator 生成用例（{tag}）")
    result = CaseGeneratorAgent().run(AgentMessage(payload=model, meta={"history": history}))
    cases: list[TestCase] = result.payload
    print(f"   共 {result.meta['cases']} 条，来源分布：{result.meta['by_source']}")
    print(f"   LLM 增强：{'开' if result.meta['llm_enabled'] else '关（纯规则生成）'}")

    _hr(f"⑤ 用例清单（{tag}）· 测试人员只需审核这一步")
    if args.markdown:
        for case in cases:
            print(case.to_markdown())
    else:
        for case in cases:
            print(f"\n[{case.priority} · {case.category} · {case.source}] {case.title}")
            for i, step in enumerate(case.steps, 1):
                print(f"   {i}. {step.describe()}")
            print(f"   预期：{case.expected}")

    if args.execute:
        _hr(f"⑥ 执行（{tag}）")
        _execute(cases, model, kb, url)


def _execute(cases: list[TestCase], model: PageModel, kb: TestKnowledgeBase, url: str) -> None:
    """把用例在真实浏览器里跑一遍，跑完把通过的沉淀进知识库。"""
    try:
        # url_override：让 v1 生成的用例能直接跑在 v2 的页面上（回归场景）
        results = CaseExecutor(headless=True).run(cases, model, url_override=url)
    except (ImportError, RuntimeError) as exc:
        print(f"   [跳过] {str(exc)[:80]}")
        return

    for r in results:
        mark = "✓" if r.ok else "✗"
        healed = f"（{len(r.healed_steps)} 步自愈）" if r.healed_steps else ""
        print(f"   {mark} {r.title}{healed}")
        if not r.ok and r.error:
            print(f"       → {r.error[:100]}")

    summary = kb.store_run_result(model, cases, results)
    print(f"   沉淀：PageModel 进 Wiki，{summary['cases_stored']} 条通过用例进 RAG"
          f"（新增 {summary['chunks_added']} 个片段）")
    print(f"   知识库累计：{kb.model_count} 个页面模型 / {kb.case_count} 条用例")


if __name__ == "__main__":
    raise SystemExit(main())
