"""Compile 层：LLM-Wiki 编译沉淀（骨架版）。

核心思想（Karpathy 的 LLM-Wiki）：知识不能「查完就走」，要编译沉淀成结构化的 wiki。
每次摄取都把内容归档成 Markdown 页、更新目录索引、记录日志、建立链接——知识越用越厚。

本版是「不依赖 LLM 的编译骨架」：
- 建立 wiki 目录结构（schema/index/log + entities/concepts/synthesis）。
- ingest 把 Document 渲染成 Markdown 页，更新 index 和 log。
- query 先查 index（Wiki 优先），未命中走 RAG 检索（RAG 兜底）。
- lint 检查死链和孤儿页面。

LLM 智能编译（总结、语义建链、实体抽取）通过 compile_with_llm 接口预留，
后续接入 LLM（Ollama/DeepSeek/OpenAI）后，把 ingest 的「渲染」升级为「编译」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..schemas import Document

# wiki 子目录
_ENTITY_DIR = "entities"
_CONCEPT_DIR = "concepts"
_SYNTHESIS_DIR = "synthesis"


def _slug(title: str) -> str:
    """把标题转成安全的文件名（保留中文/字母/数字，其余转下划线）。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", title).strip("_")
    return s or "untitled"


def _render_document(document: Document) -> str:
    """把 Document 渲染成 Markdown（按 block_type 组织，保留代码缩进/表格结构）。"""
    lines = [
        "---",
        f"source: {document.source}",
        f"source_type: {document.source_type}",
        f"title: {document.title}",
        "---",
        "",
        f"# {document.title}",
        "",
    ]
    for c in document.chunks:
        btype = c.metadata.get("block_type", "text")
        if btype == "heading":
            lines.append(f"## {c.text}")
        elif btype == "code":
            lines.append("```")
            lines.append(c.text)
            lines.append("```")
        elif btype == "table":
            lines.append(c.text)
        elif btype == "image":
            lines.append(f"> {c.text}")
        else:
            lines.append(c.text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


@dataclass
class WikiPage:
    """一个 wiki 页：相对路径 + 标题 + 内容。"""
    path: str
    title: str
    content: str


class WikiStore:
    """LLM-Wiki 存储：目录结构 + 归档 + 索引 + 日志 + 检查。"""

    def __init__(self, wiki_dir: Path) -> None:
        self.dir = Path(wiki_dir)
        self._ensure_structure()

    # ---- 目录结构 ----
    def _ensure_structure(self) -> None:
        for sub in (_ENTITY_DIR, _CONCEPT_DIR, _SYNTHESIS_DIR):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        if not (self.dir / "index.md").exists():
            (self.dir / "index.md").write_text("# 知识库索引\n\n", encoding="utf-8")
        if not (self.dir / "log.md").exists():
            (self.dir / "log.md").write_text("# 变更日志\n\n", encoding="utf-8")
        if not (self.dir / "schema.md").exists():
            self._write_schema()

    def _write_schema(self) -> None:
        """写结构规则文件（LLM 编译时读取的契约）。"""
        schema = """# Wiki 结构规则（schema）

- `index.md`：内容目录，每个源一条 `- [[标题]] -> 相对路径`。
- `log.md`：追加式变更日志，每条 `- 日期 动作 描述`。
- `entities/`：实体页（人/组织/产品/技术）。
- `concepts/`：概念页（理论/方法/术语）。
- `synthesis/`：跨源综合分析页。
- 页面用 `[[wikilink]]` 双向链接。
"""
        (self.dir / "schema.md").write_text(schema, encoding="utf-8")

    # ---- 归档 ----
    def ingest(self, document: Document) -> str:
        """把一份 Document 归档成 wiki 页，更新 index 和 log，返回相对路径。"""
        rel_path = f"{_CONCEPT_DIR}/{_slug(document.title)}.md"
        content = _render_document(document)

        (self.dir / rel_path).write_text(content, encoding="utf-8")

        # 更新 index
        self._append_index(f"- [[{document.title}]] -> {rel_path}\n")

        # 追加 log
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._append_log(f"- {stamp} ingest {document.title}（{len(document.chunks)} chunks）\n")

        return rel_path

    def _append_index(self, line: str) -> None:
        path = self.dir / "index.md"
        if line.strip() not in path.read_text(encoding="utf-8"):
            with path.open("a", encoding="utf-8") as f:
                f.write(line)

    def _append_log(self, line: str) -> None:
        with (self.dir / "log.md").open("a", encoding="utf-8") as f:
            f.write(line)

    # ---- 查询（Wiki 优先） ----
    def query(self, q: str) -> list[WikiPage]:
        """在 wiki 里按标题匹配查询，返回命中的页面。"""
        results: list[WikiPage] = []
        for page_path in self._list_pages():
            title = _slug_to_title(page_path)
            if q.lower() in title.lower():
                results.append(self._load_page(page_path))
        return results

    # ---- 检查 ----
    def lint(self) -> list[str]:
        """检查死链和孤儿页面，返回问题列表。"""
        issues: list[str] = []
        index_text = (self.dir / "index.md").read_text(encoding="utf-8")

        # 死链：index 里引用的文件不存在
        for m in re.finditer(r"->\s*(\S+)", index_text):
            target = m.group(1)
            if not (self.dir / target).exists():
                issues.append(f"死链：index.md 引用了不存在的 {target}")

        # 孤儿页面：存在于目录但不在 index
        for page_path in self._list_pages():
            if page_path not in index_text:
                issues.append(f"孤儿页面：{page_path} 未收录进 index.md")

        return issues

    # ---- 辅助 ----
    def _list_pages(self) -> list[str]:
        pages: list[str] = []
        for sub in (_ENTITY_DIR, _CONCEPT_DIR, _SYNTHESIS_DIR):
            for p in sorted((self.dir / sub).glob("*.md")):
                pages.append(str(p.relative_to(self.dir)))
        return pages

    def _load_page(self, rel_path: str) -> WikiPage:
        content = (self.dir / rel_path).read_text(encoding="utf-8")
        title = _slug_to_title(rel_path)
        return WikiPage(path=rel_path, title=title, content=content)

    def list_pages(self) -> list[str]:
        return self._list_pages()


def _slug_to_title(rel_path: str) -> str:
    """从相对路径反推标题（去目录和后缀）。"""
    return Path(rel_path).stem
