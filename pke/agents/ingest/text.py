"""文本 / Markdown 摄取器 —— 摄取 Agent 里最简单的一种。

纯文本和 Markdown 本来就「干净」，几乎不用「洗」。
但它也有一个坑：Markdown 里的代码块（``` 包裹）和标题结构，
如果当成普通文本按空行切分，代码缩进和标题层级会被破坏。

所以这里的职责是：按 Markdown 结构分块（标题 / 段落 / 代码块），
代码块原样保留，标题层级记入 metadata 供下游溯源。
"""
from __future__ import annotations

from pathlib import Path

from ...schemas import Document


def _is_md(path: Path) -> bool:
    return path.suffix.lower() in (".md", ".markdown")


def ingest_text(path: str | Path) -> Document:
    """把纯文本或 Markdown 摄取成结构化 Document。

    - Markdown：按标题 / 代码块 / 段落分块，代码块保留原始内容，标题层级记入 section。
    - 纯文本：按空行分段。
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    doc = Document(source=str(path), source_type="text", title=path.stem)

    if not _is_md(path):
        # 纯文本：按空行分段
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                doc.add_chunk(para, block_type="text")
        return doc

    # Markdown：逐行解析，识别代码块和标题
    lines = text.split("\n")
    buf: list[str] = []
    in_code = False
    current_section = ""

    def _flush(block_type: str = "text") -> None:
        nonlocal buf
        content = "\n".join(buf).strip()
        if content:
            doc.add_chunk(content, block_type=block_type, section=current_section)
        buf = []

    for line in lines:
        # 代码块边界
        if line.strip().startswith("```"):
            if in_code:
                _flush("code")
                in_code = False
            else:
                _flush("text")
                in_code = True
            continue

        if in_code:
            buf.append(line)  # 代码块内容原样保留（缩进/换行不动）
            continue

        # 标题：更新 section，标题本身也作为一个块
        if line.startswith("#"):
            _flush("text")
            level = len(line) - len(line.lstrip("#"))
            title = line.lstrip("#").strip()
            current_section = title
            doc.add_chunk(title, block_type="heading", section=title, level=level)
            continue

        buf.append(line)

    _flush("text")
    return doc
