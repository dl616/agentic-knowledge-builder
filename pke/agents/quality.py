"""Quality Agent：知识质检——诊断报告点名的缺口。

对应专家诊断的核心洞察：「自动化测试不是拿到需求后第一件事，
先要判断测什么、怎么判断通过」——映射到知识域：
「摄取不是拿到文档就编译，先要判断这份内容干不干净、能不能当稳定知识」。

职责边界（诚实说明，不过度设计）：
- 检测「机械性」问题：空 chunk、乱码率、扫描件占比、异常短文档。
- 不做「语义性」判断（这份内容对不对、矛盾不矛盾）——那需要 LLM，
  留给后续接入 LLM 后的 Compile 层升级（lint 检测矛盾）。
- 质检结果决定 Router.classify_tier 的走向：不通过 → 强制 cold（只进 RAG，不进 Wiki）。

输入：AgentMessage(payload=Document)
输出：AgentMessage(payload=Document, meta 含 passed / issues)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..schemas import Document
from .base import Agent, AgentMessage

# 乱码判定：非常见字符（非中英文数字标点）占比超过此阈值，视为乱码
_GARBLED_RATIO_THRESHOLD = 0.3
# 单个 chunk 正文过短（几乎无信息量）的字符数下限
_MIN_CHUNK_SIZE = 2


@dataclass
class QualityReport:
    """一次质检的结果：是否通过 + 具体问题清单，可审计不是黑箱。"""
    passed: bool
    issues: list[str] = field(default_factory=list)
    empty_chunk_count: int = 0
    garbled_chunk_count: int = 0


def _is_garbled(text: str) -> bool:
    """粗略判断一段文字是否乱码：可打印常见字符占比过低。"""
    if not text:
        return False
    _punct = "，。！？、；：""''（）()[]{}.,!?;:-_/"
    normal = sum(1 for ch in text if ch.isalnum() or ch.isspace() or ch in _punct)
    return (1 - normal / len(text)) > _GARBLED_RATIO_THRESHOLD


def inspect(document: Document) -> QualityReport:
    """对一份 Document 做质检，返回结构化报告。"""
    issues: list[str] = []
    empty_count = 0
    garbled_count = 0

    if not document.chunks:
        issues.append("文档摄取后没有任何 chunk，可能是空文件或解析失败")

    for i, c in enumerate(document.chunks):
        if len(c.text.strip()) < _MIN_CHUNK_SIZE:
            empty_count += 1
        elif _is_garbled(c.text):
            garbled_count += 1
            issues.append(f"chunk[{i}] 疑似乱码：{c.text[:20]!r}...")

    if empty_count > 0:
        issues.append(f"共 {empty_count} 个近空 chunk（可能是解析残留）")

    scanned_pages = document.meta.get("needs_ocr_pages", [])
    if scanned_pages:
        issues.append(
            f"含 {len(scanned_pages)} 个扫描件页面（{scanned_pages}），未做 OCR，内容不完整"
        )

    total = max(len(document.chunks), 1)
    garbled_ratio = garbled_count / total
    passed = garbled_ratio < 0.5 and bool(document.chunks)

    return QualityReport(
        passed=passed,
        issues=issues,
        empty_chunk_count=empty_count,
        garbled_chunk_count=garbled_count,
    )


class QualityAgent(Agent):
    name = "quality"

    def run(self, msg: AgentMessage) -> AgentMessage:
        document = msg.payload
        if not isinstance(document, Document):
            raise TypeError(f"QualityAgent 期望 Document，收到 {type(document)!r}")

        report = inspect(document)
        return AgentMessage(
            payload=document,
            meta={
                "passed": report.passed,
                "issues": report.issues,
                "empty_chunk_count": report.empty_chunk_count,
                "garbled_chunk_count": report.garbled_chunk_count,
            },
        )
