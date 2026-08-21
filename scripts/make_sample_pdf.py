"""生成一份「内容已知」的测试 PDF。

这是整个项目的方法论核心：验证摄取器对不对，不靠猜，靠一份已知答案的样本。
这份 PDF 里刻意塞进了所有会咬人的元素：

- 中文段落（会被文本框自动折行 → 产生「软换行」，考验段落重建）
- 英文段落
- 一个 3x3 表格（考验表格还原）
- 一段带缩进的 Python 代码（考验缩进保留，真正的解法在 Step 4）
- 特殊符号（数学符号、希腊字母、中文标点、摄氏度——考验转义破坏）
- 一张纯色图片（图片里的信息，文本提取是盲区，考验图片抠出 + 后续 OCR）

运行：python scripts/make_sample_pdf.py
输出：data/raw/sample.pdf
"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "sample.pdf"


def _draw_table(page: fitz.Page, x0: float, y0: float, rows: list[list[str]]) -> float:
    """画一个带格线的表格，返回表格底部 y 坐标。"""
    col_w = 110
    row_h = 26
    n_rows = len(rows)
    n_cols = len(rows[0])
    x1 = x0 + col_w * n_cols
    y1 = y0 + row_h * n_rows

    for i in range(n_rows + 1):
        y = y0 + i * row_h
        page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=0.6)
    for j in range(n_cols + 1):
        x = x0 + j * col_w
        page.draw_line((x, y0), (x, y1), color=(0, 0, 0), width=0.6)

    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            page.insert_text(
                (x0 + j * col_w + 6, y0 + i * row_h + 17),
                cell,
                fontsize=11,
                fontname="china-s",
            )
    return y1


def main() -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    x, y = 72, 72

    # 标题
    page.insert_text((x, y), "Personal Knowledge Engine 测试文档", fontsize=20, fontname="china-s")
    y += 44

    # 中文段落（用 textbox 让 PyMuPDF 自动折行，制造软换行）
    cn = (
        "这是一个用于验证知识录入可靠性的测试文档。"
        "它的作用不是承载真实知识，而是故意制造各种排版陷阱，"
        "让摄取器在这些陷阱上暴露问题：段落折行、表格、代码缩进、特殊符号、"
        "以及藏在图片里的文字。只有当摄取器能把这些元素都干净地还原出来，"
        "我们才有信心让它去处理真实资料。"
    )
    rect = fitz.Rect(x, y, x + 460, y + 90)
    page.insert_textbox(rect, cn, fontsize=12, fontname="china-s")
    y += 100

    # 英文段落
    en = (
        "The hardest part of any RAG system is not the model, "
        "but how knowledge enters, persists, and is retrieved without losing context. "
        "This sample exists to stress that pipeline."
    )
    rect = fitz.Rect(x, y, x + 460, y + 60)
    page.insert_textbox(rect, en, fontsize=11, fontname="china-s")
    y += 70

    # 表格
    table = [
        ["姓名", "年龄", "城市"],
        ["张三", "28", "深圳"],
        ["李四", "35", "北京"],
        ["王五", "42", "上海"],
    ]
    y = _draw_table(page, x, y, table) + 24

    # 代码块（等宽字体，保留缩进）
    code = (
        "def fib(n):\n"
        "    if n <= 1:\n"
        "        return n\n"
        "    return fib(n - 1) + fib(n - 2)\n"
    )
    rect = fitz.Rect(x, y, x + 460, y + 80)
    page.insert_textbox(rect, code, fontsize=10, fontname="cour")
    y += 90

    # 特殊符号
    symbols = "E = mc²  ·  α + β = γ  ·  √2 ≈ 1.414  ·  37.5°C  ·  「中文引号」《书名号》"
    page.insert_text((x, y), symbols, fontsize=12, fontname="china-s")
    y += 36

    # 一张纯色图片（图片里的信息是文本提取盲区）
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 120, 60))
    pix.set_rect(pix.irect, (210, 225, 255))
    page.insert_image(fitz.Rect(x, y, x + 120, y + 60), pixmap=pix)
    page.insert_text(
        (x + 140, y + 35),
        "← 一张纯色图：里面的像素信息，文本提取看不见（待 Step 3 OCR）",
        fontsize=10,
        fontname="china-s",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    doc.close()
    print(f"已生成测试 PDF：{OUT}")


if __name__ == "__main__":
    main()
