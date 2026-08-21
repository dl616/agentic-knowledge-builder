"""pytest 共享 fixture。

核心方法论「已知样本断言」：测试不靠猜，先造内容已知的样本，
再断言摄取结果逐项正确。
"""
from __future__ import annotations

import pymupdf as fitz
import pytest


@pytest.fixture
def sample_pdf_path(tmp_path) -> str:
    """生成一份内容已知的 PDF：含正文段落 + 代码块 + 表格。

    代码块用等宽字体（Cour），正文用普通字体——用来验证
    摄取器能否正确区分代码块并保留缩进换行。
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    x, y = 72, 72

    # 正文段落
    page.insert_textbox(
        fitz.Rect(x, y, x + 460, y + 60),
        "这是一段用于验证软换行合并的正文内容。",
        fontsize=12,
        fontname="china-s",
    )
    y += 80

    # 代码块（等宽字体）
    code = "def fib(n):\n    if n <= 1:\n        return n\n    return fib(n - 1) + fib(n - 2)\n"
    page.insert_textbox(fitz.Rect(x, y, x + 460, y + 80), code, fontsize=10, fontname="cour")

    path = tmp_path / "sample.pdf"
    doc.save(path)
    doc.close()
    return str(path)
