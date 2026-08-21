"""统一数据契约：Document 与 Chunk。

这是整个项目的「唯一真相」——所有 Agent 通过它通信，所有适配器从它出发转换。

一个常见的 RAG 反模式：摄取器直接把「文档 → 一堆字符串」，
来源、页码、标题这些元数据在拆分时被丢掉。结果就是——
检索到了一个片段，却不知道它出自哪篇原文、哪个章节、哪个位置，
答案无法溯源，上下文「断了」。

这里的做法：从摄取那一刻起，就让每个知识原子（Chunk）自带完整出身信息。

设计原则：
1. 一份资料 = 一个 Document（来源统一、出处可指）。
2. 一个 Document = 若干 Chunk（最小可检索单元）。
3. 每个 Chunk 的 metadata 必须能回答：「这段文字是谁、在哪、什么类型」。
4. metadata 显式声明、类型明确，不靠字典猜。
5. 改契约 = 改 schema 版本号，触发全量重摄取（契约即真相）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

# 数据契约版本号：契约字段变更时 +1，并触发全量重摄取
SCHEMA_VERSION = 1

# 摄取来源类型（对应 agents/ingest/ 下每个解析器）
SOURCE_TYPES = ("pdf", "web", "image", "code", "text")


@dataclass
class Chunk:
    """知识的最小可检索单元。

    text      : 该 chunk 的正文（干净、无乱码、无转义破坏）。
    metadata  : 出身信息，检索、溯源、去重全靠它。
    chunk_id  : 全局唯一标识，用于引用标注 [1][2][3] 和去重。
    """

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        # 规范化：正文永远干净，两侧空白去掉，但内部换行/缩进保留
        # （换行和缩进对代码、公式、诗歌是有意义的，不能无脑 strip 掉内部结构）
        self.text = self.text.strip("\n ").strip()

    @property
    def size(self) -> int:
        """正文长度（字符数），分块时据此判断边界。"""
        return len(self.text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Document:
    """一份原始资料摄取后的结构化结果。

    source       : 原始出处（本地路径或 URL），溯源的根本。
    source_type  : 属于 SOURCE_TYPES 中的哪种。
    title        : 资料标题，索引与展示用。
    chunks       : 拆分后的知识原子。
    meta         : 资料级元数据（作者、日期、语言、总页数……）。
    """

    source: str
    source_type: str
    title: str = ""
    chunks: list[Chunk] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"未知来源类型 {self.source_type!r}，应为 {SOURCE_TYPES} 之一")

    def add_chunk(
        self,
        text: str,
        *,
        page: int | None = None,
        block_type: str = "text",
        section: str = "",
        **extra: Any,
    ) -> Chunk:
        """新增一个 chunk，并自动注入出身信息。

        调用方只需给正文，元数据由这里统一拼装，
        保证每个 chunk 都有 source / source_type / page / block_type 这几个关键字段，
        从源头避免「某个 chunk 没记来源」的遗漏。
        """
        meta: dict[str, Any] = {
            "source": self.source,
            "source_type": self.source_type,
            "title": self.title,
            "block_type": block_type,   # text / table / image / code ...
            "section": section,
        }
        if page is not None:
            meta["page"] = page
        meta.update(extra)

        chunk = Chunk(text=text, metadata=meta)
        self.chunks.append(chunk)
        return chunk

    @property
    def total_size(self) -> int:
        """所有 chunk 的正文总长，用于判断摄取是否「吃进去了」。"""
        return sum(c.size for c in self.chunks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "title": self.title,
            "meta": self.meta,
            "chunks": [c.to_dict() for c in self.chunks],
        }
