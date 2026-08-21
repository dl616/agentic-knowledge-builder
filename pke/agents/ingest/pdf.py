"""PDF 摄取器 —— 摄取 Agent 里最硬的一种解析，也是最典型的坑。

为什么 PDF 最难啃？因为 PDF 是「打印格式」，不是「文档格式」：
它记录的是「这个字画在页面的 (x, y) 坐标上」，而不是「这是一段话的第 3 行」。
所以「读 PDF」本质上是在逆向工程排版。

这里要解决的坑：

1. 文本 vs 排版：用 get_text("dict") 拿块级结构，而不是 get_text() 拿一坨字符串。
   —— get_text() 会按 PDF 内部顺序吐字，双栏、文本框、页眉页脚会乱序混在一起。

2. 段落重建：dict 里的 text block 只是「视觉上靠在一起的行」，
   段内的软换行（一行没写完换到下一行）需要合并成一句话，否则每个半行都变成一个碎片。

3. 表格：普通的文本提取会把表格的格子拆散成乱序文字。
   PyMuPDF 的 find_tables() 能检测表格线，还原成结构化矩阵。

4. 图片：图片里的文字，文本提取根本看不到——需要单独把图片抠出来，交给 OCR。

5. 扫描件：整页只有图、没有文本层（比如扫描的纸质书），
   检测到「文本字符极少」就要标记 needs_ocr，不能假装提取成功。

6. 元数据溯源：每一段文字都要带上「页码 + 块类型」，检索时才指得回原文。
"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from ...config import PDF_OCR_THRESHOLD
from ...scanner import _is_mono
from ...schemas import Document

# 段尾标点：用于判断一行是不是段落结束，决定软换行 vs 段间换行
_SENTENCE_END = "。！？!?.;；:："


def _block_is_code(block: dict) -> bool:
    """判断一个 text block 是不是代码块（按等宽字体占比）。

    代码和正文的排版方式根本不同：
    - 正文：一段话折成多行，那些换行是「软换行」，该合并。
    - 代码：每一行换行、每一格缩进都是语义（Python 靠缩进定层级），一个都不能动。

    区分它们的可靠信号是字体：代码几乎都用等宽字体渲染。
    """
    spans = [s for line in block.get("lines", []) for s in line.get("spans", [])]
    if not spans:
        return False
    mono = sum(1 for s in spans if _is_mono(s.get("font", "")))
    return mono / len(spans) >= 0.8   # 80% 以上 span 是等宽字体 → 视为代码块


def _rebuild_paragraph(block: dict) -> str:
    """把一个 text block 里的多行，重建为可读的段落（代码块除外）。

    block["lines"] 是视觉上的行。PDF 里一段话在页面宽度不够时会被折成多行，
    这些「软换行」不该保留（否则一句话被拆成两段碎片）。

    启发式：上一行末尾若是段尾标点，说明这句话真的结束了 → 换行；
    否则视为软换行 → 用空格连接。
    例外：代码块保留原始换行和缩进，一个字符都不动。
    """
    lines = []
    for line in block.get("lines", []):
        # 一行可能含多个 span（不同字体/颜色），拼起来就是这一行的完整文字
        text = "".join(span.get("text", "") for span in line.get("spans", []))
        lines.append(text.rstrip())

    if not lines:
        return ""

    # 代码块：换行和缩进是语义本身，原样保留，绝不合并
    if _block_is_code(block):
        return "\n".join(lines).strip("\n")

    parts = [lines[0]]
    for prev, cur in zip(lines, lines[1:], strict=False):
        if prev and prev[-1] in _SENTENCE_END:
            parts.append(cur)          # 真段尾 → 换行
        else:
            parts[-1] += " " + cur     # 软换行 → 空格连接
    return "\n".join(parts).strip()


def _extract_images(doc: fitz.Document, page: fitz.Page, image_dir: Path) -> list[dict]:
    """抠出当前页的所有图片，保存到 image_dir，返回图片元信息。

    图片里的文字是文本提取的盲区，先把它原样存档，OCR 交给 image 解析器。
    """
    out = []
    image_dir.mkdir(parents=True, exist_ok=True)
    for xref in page.get_images(full=True):
        xref = xref[0]  # get_images 返回 (xref, smask, w, h, bpc, cs, ...)
        try:
            info = doc.extract_image(xref)
        except Exception:
            continue
        ext = info.get("ext", "png")
        filename = f"img_p{page.number + 1}_x{xref}.{ext}"
        (image_dir / filename).write_bytes(info["image"])
        out.append({
            "xref": xref,
            "file": filename,
            "width": info.get("width"),
            "height": info.get("height"),
        })
    return out


def ingest_pdf(
    path: str | Path,
    *,
    extract_images: bool = True,
    image_dir: str | Path | None = None,
) -> Document:
    """把一份 PDF 摄取成结构化 Document。

    返回的 Document 里：
    - 每个文本段落 / 表格是一个 Chunk，metadata 带 page 和 block_type。
    - 图片被抠出存档，图片 chunk 记录文件位置（OCR 待 image 解析器）。
    - 扫描页（无文本层）被记入 meta["needs_ocr_pages"]。
    """
    path = Path(path)
    doc = fitz.open(path)

    meta = doc.metadata or {}
    title = meta.get("title") or path.stem
    document = Document(
        source=str(path),
        source_type="pdf",
        title=title,
        meta={
            "pages": doc.page_count,
            "author": meta.get("author"),
            "creator": meta.get("creator"),
            "format": meta.get("format"),
        },
    )

    if image_dir is None:
        image_dir = path.parent / "assets"
    image_dir = Path(image_dir)

    needs_ocr: list[int] = []

    for page in doc:  # type: ignore[attr-defined]  # pymupdf Document 可迭代，stub 缺 __iter__
        pno = page.number + 1  # 页码从 1 开始，人类友好

        # --- 文本块 ---
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:   # 0 = 文本块
                continue
            is_code = _block_is_code(block)
            text = _rebuild_paragraph(block)
            if text:
                document.add_chunk(
                    text,
                    page=pno,
                    block_type="code" if is_code else "text",
                )

        # --- 表格 ---
        try:
            for table in page.find_tables().tables:
                rows = table.extract()   # list[list[str]]
                if not rows:
                    continue
                # 表格压成带制表符的文本，保留行列结构
                table_text = "\n".join("\t".join(str(c or "") for c in row) for row in rows)
                document.add_chunk(
                    table_text,
                    page=pno,
                    block_type="table",
                    rows=len(rows),
                    cols=len(rows[0]) if rows else 0,
                )
        except Exception:
            # find_tables 在无表格的页会正常返回空，这里兜底异常不中断整份摄取
            pass

        # --- 图片 ---
        if extract_images:
            for img in _extract_images(doc, page, image_dir):
                document.add_chunk(
                    f"[图片 {img['file']}]",
                    page=pno,
                    block_type="image",
                    **img,
                )

        # --- 扫描页检测 ---
        if len(page.get_text().strip()) < PDF_OCR_THRESHOLD:
            needs_ocr.append(pno)

    if needs_ocr:
        document.meta["needs_ocr_pages"] = needs_ocr

    doc.close()
    return document
