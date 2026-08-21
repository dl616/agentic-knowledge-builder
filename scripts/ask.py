"""问答演示 CLI：摄取 → 索引 → 提问 → 带引用回答。

用法：
    python scripts/ask.py <文件路径> <查询>

演示完整的问答闭环：
1. 识别文件类型并摄取成结构化 Document
2. Index Agent 建立检索索引
3. Retrieval + Answer Agent 召回相关片段，组装带引用的回答
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pke.agents import AnswerAgent, IndexAgent
from pke.agents.base import AgentMessage
from pke.knowledge import RagKnowledgeBase
from pke.scanner import scan


def ingest_file(path: Path):
    """按类型摄取一个文件（复用 scripts/ingest.py 的路由逻辑）。"""
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
    if len(sys.argv) < 3:
        print("用法：python scripts/ask.py <文件路径> <查询>")
        sys.exit(1)

    path = Path(sys.argv[1])
    query = sys.argv[2]

    # 1. 摄取
    doc = ingest_file(path)
    print(f"[摄取] {doc.title}（{len(doc.chunks)} 个 chunk）")

    # 2. 索引
    kb = RagKnowledgeBase()
    index = IndexAgent(kb)
    index_result = index.run(AgentMessage(payload=doc))
    print(f"[索引] 知识库共 {index_result.meta['total_chunks']} 个 chunk")

    # 3. 检索 + 问答
    answer = AnswerAgent(kb)
    answer_result = answer.run(AgentMessage(payload=query))

    print("\n" + "=" * 60)
    print(f"问题：{query}")
    print("=" * 60)
    result = answer_result.payload
    if not result.results:
        print("（未找到相关内容）")
    else:
        print("\n【检索到的相关片段】\n")
        print(result.context)
        print("\n【出处】")
        for c in result.citations:
            page = f"，第 {c['page']} 页" if c.get("page") else ""
            print(f"  [{c['index']}] 来自 {c['source']}{page}（{c['block_type']}）")


if __name__ == "__main__":
    main()
