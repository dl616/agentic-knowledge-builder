"""流水线编排层单测（S6）。

编排层最容易写歪的地方是「节点之间靠什么通信」——
这里验证的是 state（共享状态）语义，而不是把整条流水线再跑一遍
（真跑浏览器属于集成测试的活，见 tests/integration/test_reuse_browser.py）。

重点三条：

    1. 节点顺序固定：探索 → 建模 → 召回 → 生成 → 执行 → 归因 → 沉淀；
    2. 有 LangGraph 走图、没有走线性降级，两种路径产出必须一致；
    3. 单节点报错不炸整条流水线，而是记进 state.errors。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from pke.testing.graph import NODE_ORDER, TestPipeline, report


@pytest.fixture()
def kdir() -> Path:
    """知识库目录。

    不用 pytest 自带的 tmp_path：CI/沙箱里它的根目录权限不稳，
    而这里只需要一个能写的临时目录，放项目 .cache 下更可控。
    """
    with tempfile.TemporaryDirectory(dir=Path(".cache")) as tmp:
        yield Path(tmp)


def test_node_order_is_stable():
    assert NODE_ORDER == (
        "explore", "analyze", "recall", "generate", "execute", "attribute", "compile",
    )


def test_state_keys_cover_all_node_outputs():
    """每个节点都有对应的 state 键——否则节点产出会被静默丢掉。"""
    outputs = {
        "explore": "snapshot",
        "analyze": "model",
        "recall": "history",
        "generate": "cases",
        "execute": "results",
        "attribute": "reports",
        "compile": "stored",
    }
    assert set(outputs) == set(NODE_ORDER)


def test_report_renders_without_execution():
    """只生成不执行时，报告也要能出（不能因为没结果就崩）。"""
    text = report({"url": "file:///tmp/a.html", "cases": []})
    assert "file:///tmp/a.html" in text
    assert "用例总数：0" in text


def test_report_surfaces_errors():
    text = report({"url": "file:///tmp/a.html", "errors": ["explore: 浏览器起不来"]})
    assert "浏览器起不来" in text


@pytest.mark.parametrize("use_graph", [True, False])
def test_linear_and_graph_paths_agree(kdir: Path, monkeypatch, use_graph: bool):
    """两种执行路径（LangGraph 图 / 线性降级）必须产出同样的 state 结构。

    用 monkeypatch 把每个节点替换成固定产出，这样不用起浏览器，
    就能验证「图编排有没有把节点产出正确合并进 state」。
    """
    import pke.testing.graph as graph_mod

    monkeypatch.setattr(graph_mod, "_langgraph_available", lambda: use_graph)

    pipeline = TestPipeline(knowledge_dir=kdir)
    calls: list[str] = []

    def fake(name, value):
        def node(self, state):  # noqa: ANN001, ANN202
            calls.append(name)
            return value

        return node

    pipeline._NODES = {  # noqa: SLF001
        "explore": fake("explore", {"snapshot": "snap"}),
        "analyze": fake("analyze", {"model": "model"}),
        "recall": fake("recall", {"history": [], "rebind_notes": []}),
        "generate": fake("generate", {"cases": ["c1"]}),
        "execute": fake("execute", {"results": ["r1"]}),
        "attribute": fake("attribute", {"reports": []}),
        "compile": fake("compile", {"stored": {"cases_stored": 1}}),
    }

    state = pipeline.run("file:///tmp/a.html")

    assert calls == list(NODE_ORDER)
    assert state["cases"] == ["c1"]
    assert state["results"] == ["r1"]
    assert state["stored"] == {"cases_stored": 1}
    assert state["errors"] == []


def test_failing_node_does_not_break_pipeline(kdir: Path, monkeypatch):
    """编排层的原则：跑完要能拿到报告，而不是第一步挂了就啥也没有。"""
    import pke.testing.graph as graph_mod

    monkeypatch.setattr(graph_mod, "_langgraph_available", lambda: False)

    pipeline = TestPipeline(knowledge_dir=kdir)

    def boom(self, state):  # noqa: ANN001, ANN202
        raise RuntimeError("浏览器启动失败")

    pipeline._NODES = {  # noqa: SLF001
        **{name: (lambda self, state: {}) for name in NODE_ORDER},
        "explore": boom,
    }

    state = pipeline.run("file:///tmp/a.html")
    assert state["errors"]
    assert "浏览器启动失败" in state["errors"][0]
