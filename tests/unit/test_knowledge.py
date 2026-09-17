"""测试知识层（S5）单测：沉淀进冷热层，第二轮能召回第一轮的资产。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pke.testing.knowledge import TestKnowledgeBase, case_to_document, model_to_document
from pke.testing.schemas import (
    BusinessAction,
    CaseResult,
    Control,
    Locator,
    PageModel,
    TestCase,
    TestStep,
)


def _signup_model(url: str = "http://localhost/signup") -> PageModel:
    """构造注册页模型（与 fixture 一致的最小集）。"""
    return PageModel(
        url=url,
        title="用户注册",
        purpose="signup",
        controls=[
            Control(
                name="手机号",
                control_type="textbox",
                locator=Locator(strategy="css", value="#phone"),
            ),
            Control(
                name="验证码",
                control_type="textbox",
                locator=Locator(strategy="css", value="#code"),
            ),
            Control(
                name="获取验证码",
                control_type="button",
                locator=Locator(strategy="css", value="#send"),
            ),
            Control(
                name="密码",
                control_type="password",
                locator=Locator(strategy="css", value="#pwd"),
            ),
            Control(
                name="注册",
                control_type="button",
                locator=Locator(strategy="css", value="#submit"),
            ),
        ],
        actions=[
            BusinessAction(
                name="提交注册",
                action_type="submit",
                control_names=["注册"],
            ),
            BusinessAction(
                name="获取验证码",
                action_type="query",
                control_names=["获取验证码"],
            ),
        ],
    )


def _case(case_id: str, title: str) -> TestCase:
    return TestCase(
        id=case_id,
        title=title,
        steps=[TestStep(action="fill", target="手机号", value="13800138000")],
        expected="注册成功",
    )


class TestDocumentConversion:
    """资产 → Document 的转换正确性。"""

    def test_model_to_document_chunks_by_control(self) -> None:
        """PageModel 按控件/动作拆 chunk，而不是整页一个。"""
        doc = model_to_document(_signup_model())
        # 1 概览 + 5 控件 + 2 动作
        assert len(doc.chunks) == 8
        control_chunks = [c for c in doc.chunks if c.metadata.get("block_type") == "control"]
        assert len(control_chunks) == 5

    def test_model_document_title(self) -> None:
        doc = model_to_document(_signup_model())
        assert doc.title == "页面模型：用户注册"
        assert doc.source_type == "test"

    def test_case_to_document_contains_semantics(self) -> None:
        """用例正文要含标题+步骤+预期，否则检索命中不了。"""
        doc = case_to_document(_case("TC-1", "手机号为空时注册失败"))
        assert len(doc.chunks) == 1
        text = doc.chunks[0].text
        assert "手机号为空时注册失败" in text
        assert "注册成功" in text


class TestStore:
    """沉淀行为。"""

    def test_store_page_model_writes_wiki(self, tmp_path: Path) -> None:
        kb = TestKnowledgeBase(tmp_path / "wiki")
        rel = kb.store_page_model(_signup_model())
        assert rel.endswith(".md")
        assert (tmp_path / "wiki" / rel).exists()

    def test_store_page_model_indexes_rag(self, tmp_path: Path) -> None:
        kb = TestKnowledgeBase(tmp_path / "wiki")
        kb.store_page_model(_signup_model())
        assert kb.chunk_count == 8
        assert kb.model_count == 1

    def test_store_cases_only_accepts_passed(self, tmp_path: Path) -> None:
        """失败用例不沉淀——它会污染召回。"""
        kb = TestKnowledgeBase(tmp_path / "wiki")
        model = _signup_model()
        cases = [_case("TC-1", "正常注册成功"), _case("TC-2", "密码过短应报错")]
        results = [
            CaseResult(case_id="TC-1", title="正常注册成功", ok=True),
            CaseResult(case_id="TC-2", title="密码过短应报错", ok=False, error="断言失败"),
        ]
        summary = kb.store_run_result(model, cases, results)
        assert summary["cases_stored"] == 1
        assert kb.case_count == 1

    def test_wiki_index_updated(self, tmp_path: Path) -> None:
        kb = TestKnowledgeBase(tmp_path / "wiki")
        kb.store_page_model(_signup_model())
        index = (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8")
        assert "用户注册" in index


class TestRecall:
    """召回与闭环复用——S5 的核心验收点。"""

    def test_empty_kb_recalls_nothing(self, tmp_path: Path) -> None:
        kb = TestKnowledgeBase(tmp_path / "wiki")
        assert kb.recall("手机号") == []

    def test_recall_hits_stored_asset(self, tmp_path: Path) -> None:
        kb = TestKnowledgeBase(tmp_path / "wiki")
        kb.store_page_model(_signup_model())
        hits = kb.recall("验证码")
        assert hits, "存进去了却召回不到，索引是坏的"
        assert any("验证码" in h.text for h in hits)

    def test_recall_returns_asset_type(self, tmp_path: Path) -> None:
        kb = TestKnowledgeBase(tmp_path / "wiki")
        kb.store_page_model(_signup_model())
        hits = kb.recall("手机号 控件")
        assert hits
        assert hits[0].asset_type.startswith("pagemodel")

    def test_second_round_reuses_first_round_cases(self, tmp_path: Path) -> None:
        """闭环复用的关键断言：v1 沉淀的用例，v2 能被召回。

        这就是「积累复用」的可验证证据——第二轮不是从零生成，
        而是带着第一轮的历史资产进场。
        """
        kb = TestKnowledgeBase(tmp_path / "wiki")

        # 第一轮：探索 v1 注册页，生成并沉淀用例
        v1_model = _signup_model("http://localhost/signup_v1")
        v1_cases = [
            _case("TC-v1-1", "手机号格式非法应提示"),
            _case("TC-v1-2", "验证码错误应提示"),
        ]
        v1_results = [
            CaseResult(case_id="TC-v1-1", title="手机号格式非法应提示", ok=True),
            CaseResult(case_id="TC-v1-2", title="验证码错误应提示", ok=True),
        ]
        kb.store_run_result(v1_model, v1_cases, v1_results)

        # 第二轮：v2 页面（控件名基本一致）
        v2_model = _signup_model("http://localhost/signup_v2")
        hits = kb.recall_for_model(v2_model)

        assert hits, "第二轮召不回任何历史资产，闭环没闭合"
        texts = " ".join(h.text for h in hits)
        # v1 沉淀的用例应当出现在召回结果里
        assert "手机号格式非法应提示" in texts or "验证码错误应提示" in texts

    def test_recall_for_model_dedups(self, tmp_path: Path) -> None:
        """多个 query 命中同一资产时只保留一条（保留最高分）。"""
        kb = TestKnowledgeBase(tmp_path / "wiki")
        kb.store_page_model(_signup_model())
        hits = kb.recall_for_model(_signup_model())
        texts = [h.text for h in hits]
        assert len(texts) == len(set(texts)), "召回结果有重复"

    def test_history_cases_returns_objects_for_generator(self, tmp_path: Path) -> None:
        """召回结果要能直接喂给 CaseGenerator（返回用例对象而非文本）。"""
        kb = TestKnowledgeBase(tmp_path / "wiki")
        v1_model = _signup_model("http://localhost/signup_v1")
        v1_cases = [_case("TC-v1-1", "手机号格式非法应提示")]
        kb.store_run_result(
            v1_model,
            v1_cases,
            [CaseResult(case_id="TC-v1-1", title="手机号格式非法应提示", ok=True)],
        )

        v2_model = _signup_model("http://localhost/signup_v2")
        history = kb.history_cases(v2_model)
        assert history, "第二轮拿不到可复用用例对象"
        assert all(isinstance(c, TestCase) for c in history)
        assert history[0].id == "TC-v1-1"

    def test_history_cases_empty_on_first_round(self, tmp_path: Path) -> None:
        """第一轮没有历史，应当干净地返回空，而不是报错。"""
        kb = TestKnowledgeBase(tmp_path / "wiki")
        assert kb.history_cases(_signup_model()) == []

    def test_recall_for_model_ranked_by_score(self, tmp_path: Path) -> None:
        kb = TestKnowledgeBase(tmp_path / "wiki")
        kb.store_page_model(_signup_model())
        hits = kb.recall_for_model(_signup_model(), top_k=5)
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True), "召回结果未按得分排序"


class TestStats:
    """观测口径。"""

    def test_counts(self, tmp_path: Path) -> None:
        kb = TestKnowledgeBase(tmp_path / "wiki")
        assert (kb.model_count, kb.case_count, kb.chunk_count) == (0, 0, 0)
        kb.store_page_model(_signup_model())
        kb.store_cases([_case("TC-1", "正常注册")], model_url="http://x")
        assert kb.model_count == 1
        assert kb.case_count == 1
        assert kb.chunk_count == 9  # 8（模型）+ 1（用例）


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
