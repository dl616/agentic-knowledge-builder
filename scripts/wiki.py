"""沉淀演示 CLI：摄取 → 编译沉淀进 Wiki → 查询 → 检查。

用法：
    python scripts/wiki.py <文件路径>

演示 Compile 层（LLM-Wiki 骨架）的完整闭环：
1. 摄取文件成结构化 Document
2. Compile Agent 沉淀成 Markdown wiki 页（更新 index + log）
3. 展示 index、查询、lint 检查结果
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pke.agents.base import AgentMessage
from pke.agents.compile import CompileAgent
from pke.config import WIKI_DIR
from pke.knowledge.compile import WikiStore
from pke.scanner import scan


def ingest_file(path: Path):
    from pke.agents.ingest import ingest_pdf, ingest_text, ingest_web

    result = scan(path)
    if result.file_type == "pdf":
        return ingest_pdf(path)
    if result.file_type in ("text", "markdown"):
        return ingest_text(path)
    if result.file_type == "web":
        return ingest_web(path)
    raise NotImplementedError(f"暂不支持 {result.file_type}")


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python scripts/wiki.py <文件路径>")
        sys.exit(1)

    path = Path(sys.argv[1])

    # 1. 摄取
    doc = ingest_file(path)
    print(f"[摄取] {doc.title}（{len(doc.chunks)} 个 chunk）")

    # 2. 沉淀进 Wiki
    wiki = WikiStore(WIKI_DIR)
    compile_agent = CompileAgent(wiki)
    result = compile_agent.run(AgentMessage(payload=doc))
    print(f"[沉淀] 已写入 wiki/{result.payload}")

    # 3. 展示
    print("\n" + "=" * 60)
    print("【index.md 内容】")
    print((WIKI_DIR / "index.md").read_text(encoding="utf-8"))

    print("【查询测试】")
    pages = wiki.query(doc.title)
    print(f"  查询「{doc.title}」命中 {len(pages)} 个页面")

    print("【lint 检查】")
    issues = wiki.lint()
    if issues:
        for i in issues:
            print(f"  ⚠️ {i}")
    else:
        print("  ✅ 无死链、无孤儿页面")


if __name__ == "__main__":
    main()
