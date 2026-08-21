"""网页摄取器 —— 摄取 Agent 里的「去噪」环节。

网页的坑：正文里夹着一堆广告、导航、相关推荐、页脚链接。
如果把整页 HTML 原样抓进来，这些噪声会污染索引——检索时召回一堆「相关推荐」而不是正文。

这里的做法：用 trafilatura（网页正文抽取的主流库）把正文从噪声里剥离出来，
同时保留标题、URL、作者、日期这些溯源信息。

两种输入：
- URL：下载后抽取（需要网络，测试时用 HTML 文件避免依赖外网）。
- 本地 HTML 文件：直接读取抽取（测试可复现）。
"""
from __future__ import annotations

from pathlib import Path

import trafilatura

from ...schemas import Document


def _extract_text(html: str) -> str:
    """抽取正文纯文本，剥掉广告/导航/评论。"""
    text = trafilatura.extract(
        html,
        include_comments=False,     # 去评论
        include_tables=True,        # 保留表格（结构化信息）
        favor_precision=True,       # 宁可少抽，不要夹带噪声
    )
    return text or ""


def ingest_web(source: str) -> Document:
    """把网页（URL 或本地 HTML 文件）摄取成结构化 Document。

    返回的 Document：
    - 正文按段落分块，metadata 带 URL 溯源。
    - meta 带作者/日期/站点，供下游过滤与溯源。
    """
    if source.startswith(("http://", "https://")):
        html = trafilatura.fetch_url(source)
        if html is None:
            raise ValueError(f"无法下载网页：{source}")
        title = source
    else:
        p = Path(source)
        html = p.read_text(encoding="utf-8")
        title = p.stem

    # 元数据：作者/日期/站点
    meta = trafilatura.extract_metadata(html)
    if meta is not None:
        title = meta.title or title
        doc_meta: dict = {
            "author": meta.author,
            "date": meta.date,
            "hostname": meta.hostname,
        }
    else:
        doc_meta = {}

    document = Document(source=source, source_type="web", title=title, meta=doc_meta)

    text = _extract_text(html)
    for para in text.split("\n\n"):
        para = para.strip()
        if para:
            document.add_chunk(para, block_type="text")

    return document
