"""识别器（Scanner）—— 摄取的第一步：先看清你给的是什么。

为什么不能只靠「文件扩展名」？
- 扩展名会骗人：`.pdf` 可能是扫描件（没有文字，只有图），也可能含表格、代码、双栏论文，
  这些决定了后面「该怎么解析」，光看 `.pdf` 三个字判断不出来。
- 所以识别器要「打开看一眼」：是数字版还是扫描版？有没有表格？有没有代码块？有几页？

这一步的识别结果，会交给 Planner（调度器）决定派哪个解析器、走什么策略。
现在先做 PDF 的深度识别，其他类型留到对应解析器落地时再补。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

from .config import PDF_OCR_THRESHOLD

# 等宽字体的名字特征（PDF 里的代码通常用等宽字体渲染）
_MONO_FONT_HINTS = (
    "cour", "consol", "mono", "menlo", "monac", "courier",
    "fira code", "jetbrains", "sf mono", "source code", "dejavu sans mono",
)

# 扩展名 → 文件大类 的粗分类（第一层判断）
_EXT_MAP = {
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".bmp": "image", ".tiff": "image",
    ".md": "markdown", ".markdown": "markdown", ".txt": "text",
    ".py": "code", ".js": "code", ".ts": "code", ".go": "code",
    ".cpp": "code", ".c": "code", ".java": "code", ".rs": "code",
    ".html": "web", ".htm": "web",
}


def _is_mono(font_name: str) -> bool:
    """判断字体名是不是等宽字体（代码块的特征）。"""
    f = font_name.lower()
    return any(h in f for h in _MONO_FONT_HINTS)


@dataclass
class ScanResult:
    """识别结果：文件是什么、有什么特征、建议用哪个解析器。"""
    path: str
    file_type: str                 # pdf / image / markdown / text / code / web
    parser: str                    # 建议的解析器名
    features: dict = field(default_factory=dict)


def _scan_pdf_features(path: Path) -> dict:
    """深度识别一份 PDF：数字版还是扫描版？有没有表格/代码？"""
    doc = fitz.open(path)
    total_text = 0
    has_code = False
    table_count = 0
    scanned_pages: list[int] = []

    for page in doc:  # type: ignore[attr-defined]  # pymupdf 的 Document 可迭代，但 stub 缺 __iter__
        pno = page.number + 1
        page_text = page.get_text()
        total_text += len(page_text.strip())

        # 扫描页 = 几乎没有文本层
        if len(page_text.strip()) < PDF_OCR_THRESHOLD:
            scanned_pages.append(pno)

        # 检测代码块：有没有等宽字体的 span
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if _is_mono(span.get("font", "")):
                        has_code = True

        # 检测表格
        table_count += len(page.find_tables().tables)

    pages = doc.page_count
    doc.close()

    avg_text = total_text / max(pages, 1)
    return {
        "pages": pages,
        "is_scanned": len(scanned_pages) == pages,   # 全部是扫描页 → 整份是扫描件
        "scanned_pages": scanned_pages,
        "has_table": table_count > 0,
        "table_count": table_count,
        "has_code": has_code,
        "avg_text_per_page": round(avg_text, 1),
    }


def scan(path: str | Path) -> ScanResult:
    """识别一份输入，返回文件类型、特征和建议解析器。"""
    path = Path(path)
    ext = path.suffix.lower()
    file_type = _EXT_MAP.get(ext, "unknown")

    if file_type == "pdf":
        features = _scan_pdf_features(path)
        # 扫描件走 OCR 路线（暂未实现，先标记），数字版走 pdf 解析器
        parser = "ocr" if features["is_scanned"] else "pdf"
        return ScanResult(str(path), "pdf", parser, features)

    # 其余类型：先按扩展名粗分类，解析器落地时再细化
    return ScanResult(str(path), file_type, file_type if file_type != "unknown" else "", {})
