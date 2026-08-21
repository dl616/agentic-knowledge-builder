"""摄取 CLI 入口。

用法：
    python scripts/ingest.py <文件路径>

按扩展名路由到对应摄取器（当前支持 .pdf），
打印摄取结果：每个 chunk 的类型、页码、正文预览，
让你直观看到「坑」被处理成什么样。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 让 scripts/ 下的脚本能直接 `python scripts/ingest.py` 运行，
# 而无需先安装 pke 包：把项目根目录加入模块搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pke.agents.ingest import ingest_pdf, ingest_text, ingest_web
from pke.scanner import scan
from pke.schemas import Document


def ingest(path: Path) -> Document:
    # 第一步：识别——先看清是什么，再决定怎么解析
    result = scan(path)
    print(f"[识别] 类型={result.file_type}  建议解析器={result.parser}")
    for k, v in result.features.items():
        print(f"       {k} = {v}")

    if result.file_type == "pdf":
        return ingest_pdf(path)
    if result.file_type in ("text", "markdown"):
        return ingest_text(path)
    if result.file_type == "web":
        return ingest_web(path)
    raise NotImplementedError(f"暂不支持 {result.file_type} 格式（图片/代码摄取在后续步骤实现）")


def _preview(text: str, width: int = 60) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python scripts/ingest.py <文件路径>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"文件不存在：{path}")
        sys.exit(1)

    doc = ingest(path)

    print("=" * 70)
    print(f"来源      : {doc.source}")
    print(f"标题      : {doc.title}")
    print(f"类型      : {doc.source_type}")
    print(f"元信息    : {doc.meta}")
    print(f"Chunk 数  : {len(doc.chunks)}")
    print(f"总字符数  : {doc.total_size}")
    print("=" * 70)

    for i, c in enumerate(doc.chunks, 1):
        page = c.metadata.get("page", "-")
        btype = c.metadata.get("block_type", "?")
        print(f"\n[{i:02d}] page={page:<4} type={btype:<6} size={c.size}")
        print(f"     {_preview(c.text)}")


if __name__ == "__main__":
    main()
