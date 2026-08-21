"""摄取 Agent 的解析器集合。

每种文件类型一个解析器，输出统一的 Document（见 pke.schemas）。
"""
from .pdf import ingest_pdf
from .text import ingest_text
from .web import ingest_web

__all__ = ["ingest_pdf", "ingest_text", "ingest_web"]
