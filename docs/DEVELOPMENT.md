# 开发架构与规范（Development Guide）

> Agentic Knowledge Builder 的工程级开发文档。定义目录结构、分层架构、核心抽象、代码/测试/评测/Git/CI 规范。
> 所有新 Agent、新模块的开发，都必须遵循本文件。

---

## Part 1 — 架构

### 1.1 项目目录结构

```
personal-knowledge-engine/
├── pyproject.toml              # 项目元数据 + 依赖（uv 管理，PEP 621）
├── README.md                   # 项目门面：是什么、为什么、怎么用
├── .gitignore
├── .github/workflows/ci.yml    # CI
├── docs/
│   ├── PRD.md                  # 产品需求（定稿 v2.0）
│   └── DEVELOPMENT.md          # 本文件：开发架构与规范
├── pke/                        # 主包
│   ├── __init__.py
│   ├── config.py               # 集中配置（路径/模型/阈值），禁散落魔法值
│   ├── scanner.py              # 识别器：识别类型 + 特征（等宽字体/表格/扫描件）
│   ├── schemas.py              # 统一数据契约：Document / Chunk / WikiPage / AgentMessage
│   ├── agents/                 # Agent 层（核心）
│   │   ├── __init__.py
│   │   ├── base.py             # Agent 抽象基类 + 统一接口 + 注册表
│   │   ├── orchestrator.py     # 总控 Agent：识别→规划→调度
│   │   ├── ingest/             # 摄取 Agent（特色：录入保真）
│   │   │   ├── __init__.py
│   │   │   ├── pdf.py          #   已实现：代码块保真/表格/图片/扫描件检测
│   │   │   ├── web.py          #   待做：正文抽取（trafilatura）
│   │   │   ├── image.py        #   待做：OCR
│   │   │   └── text.py         #   待做：Markdown/纯文本（几乎不用洗）
│   │   ├── quality.py          # 质检 Agent：丢字/乱码/残缺检测 + 纠错
│   │   ├── index.py            # 索引 Agent：分块 + 嵌入 + 写入
│   │   ├── retrieval.py        # 检索 Agent：混合检索 + 重排
│   │   └── answer.py           # 问答 Agent：带引用生成
│   ├── knowledge/              # 三层知识架构（查存混合）
│   │   ├── __init__.py
│   │   ├── compile.py          #   Compile 层：LLM-Wiki 编译沉淀
│   │   ├── rag.py              #   RAG 层：向量库检索
│   │   ├── memory.py           #   Memory 层：用户记忆
│   │   └── router.py           #   路由：定义/综合类 vs 精确查找类 + 回流
│   └── adapters/               # 输出适配器（中间格式 → 各下游）
│       ├── __init__.py
│       ├── json_adapter.py     #   → 向量库
│       ├── markdown_adapter.py #   → LLM-Wiki / Obsidian
│       └── text_adapter.py     #   → 全文检索
├── scripts/                    # CLI 入口
│   └── ingest.py
├── tests/                      # 测试
│   ├── unit/                   #   单元测试（每个 Agent/模块一个文件）
│   ├── integration/            #   集成测试（跨 Agent 链路）
│   └── fixtures/               #   已知内容测试样本（断言法的核心）
├── eval/                       # 评测（与测试分离）
│   ├── dataset/                #   评测集（脏样本 + 标准答案）
│   └── ragas_eval.py           #   RAGAs 评测脚本
└── data/                       # 运行时数据（gitignore）
    ├── raw/                    #   原始资料
    └── wiki/                   #   编译沉淀的知识
```

### 1.2 分层架构

```
接入层：CLI / FastAPI（后续）
   ↓
Agent 层：Orchestrator → [Ingest · Quality · Index · Retrieval · Answer]
   ↓
知识层：Compile(LLM-Wiki) / RAG(向量) / Memory(记忆) + Router
   ↓
能力层：解析(Docling/PyMuPDF) · 嵌入 · 混合检索 · Rerank
   ↓
数据层：Qdrant · Markdown Wiki · SQLite(起步)
   ↓
模型层：可插拔 Adapter（Ollama/DeepSeek/OpenAI）
```

**依赖方向**：只能上层依赖下层，禁止反向依赖。`agents/` 可依赖 `knowledge/` 和 `scanner.py`，但 `knowledge/` 不得依赖 `agents/`。

### 1.3 核心抽象

#### 数据契约（`schemas.py`）

```python
@dataclass
class Chunk:
    text: str                      # 干净正文（代码保留缩进换行）
    metadata: dict                 # source/page/block_type/section/lang
    chunk_id: str                  # 全局唯一，用于引用标注

@dataclass
class Document:
    source: str                    # 原始出处（路径/URL）
    source_type: str               # pdf/web/image/text/code
    title: str
    chunks: list[Chunk]
    meta: dict
```

**契约是「唯一真相」**：所有 Agent 通过它通信，所有适配器从它出发。改契约 = 改 schema 版本号，触发全量重摄取。

#### Agent 接口（`agents/base.py`）

```python
class Agent(ABC):
    name: str                      # 唯一标识
    def run(self, msg: AgentMessage) -> AgentMessage: ...
```

- 每个 Agent 是**纯函数式**的：输入 `AgentMessage`，输出 `AgentMessage`，无隐藏副作用。
- Agent 之间**不直接互相调用**，统一由 Orchestrator 调度（Orchestrator-Worker 模式）。
- 新增 Agent = 继承 `Agent` + 注册到 Orchestrator 的注册表，不修改已有代码。

### 1.4 数据流

```
输入 → scanner.识别 → orchestrator.规划 → ingest.解析 → quality.质检
                                                    ↓
                                              (通过/回退重试)
                                                    ↓
                          index.分块+嵌入 ──→ 知识层(RAG/Compile/Memory)
                                                    ↓
用户提问 → router.路由 → retrieval.检索 + compile.读Wiki → answer.带引用生成
```

---

## Part 2 — 规范

### 2.1 代码规范

| 项 | 规范 |
|---|---|
| Python | 3.12+ |
| 格式化/静态检查 | **ruff**（format + lint 一体），配置在 `pyproject.toml` |
| 类型注解 | 全量类型注解，`from __future__ import annotations`；CI 跑 `mypy --strict` |
| 命名 | 模块/函数 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE` |
| docstring | 公共函数必须有：一句话说明 + 关键坑（见 `pke/ingest/pdf.py` 现有风格） |
| 注释 | 解释「为什么」，不解释「是什么」 |
| 禁止 | 裸 `except`、散落魔法值（统一进 `config.py`）、硬编码路径 |

### 2.2 测试规范

- 框架：**pytest**，覆盖率门槛 **85%**（`pytest-cov`）。
- 三层测试：
  1. **单元测试**（`tests/unit/`）：每个 Agent/模块一个文件，mock LLM 与向量库。
  2. **集成测试**（`tests/integration/`）：跨 Agent 链路（如 ingest→quality→index）。
  3. **已知样本断言**（`tests/fixtures/`）：**核心方法论**——先造内容已知的脏样本，断言提取/检索结果逐项正确，不靠肉眼。
- 命令：`uv run pytest --cov=pke --cov-report=term-missing`。

### 2.3 评测规范（与测试分离）

- 测试验证「对不对」（正确性），评测度量「好不好」（质量）。
- **自建评测集**（`eval/dataset/`）：脏样本 + 标准答案，指标=保真率/命中率/忠实度。
- **RAGAs**：检索质量（context precision/recall）+ 生成质量（faithfulness/answer relevancy）。
- 每完成一个里程碑，跑一次评测并记录指标到 `docs/`，能力提升「用数据说话」。

### 2.4 Git 规范

- 分支：`main`（稳定）+ `feat/*`、`fix/*` 短分支，PR 合入。
- Commit message：**Conventional Commits**——`feat: / fix: / docs: / test: / refactor: / chore:`。
- 一个 commit 只做一件事；`data/`、`.venv/`、`__pycache__/` 进 `.gitignore`。

### 2.5 依赖管理

- 用 **uv**（`pyproject.toml` + `uv.lock`），锁定版本可复现。
- 分组管理：`[project.dependencies]` 核心依赖；`[dependency-groups]` 分 `dev`（pytest/ruff/mypy）、`eval`（ragas）。
- 摄取依赖按需装（`pymupdf` 起步，网页/OCR 再加），不一次性全装。

### 2.6 CI/CD（`.github/workflows/ci.yml`）

```
on: [push, pull_request]
jobs:
  lint:     uv run ruff check .
  type:     uv run mypy pke
  test:     uv run pytest --cov=pke
```
三项全绿才可合入。后续可加 `release`（打 tag 发布到 PyPI）。

### 2.7 日志与错误处理

- 用 `logging`，不用 `print`；Agent 边界打结构化日志（`agent=`, `step=`, `source=`）。
- 错误分两层：**可恢复**（单页解析失败 → 记录 + 跳过，不中断整份摄取）；**致命**（契约违例 → 抛异常 + 触发质检回退）。
- 禁止吞异常：`except` 必须记录或重抛，附上下文。

---

## Part 3 — 开发节奏（每个 Agent 的落地流程）

1. **讲清原理**：这一步解决什么坑、为什么这么做（术语+大白话并排）。
2. **最小实现**：可运行、可验证，不铺开。
3. **已知样本断言**：先造样本，断言正确性。
4. **三件套收尾**：单测 + 更新 PRD 里程碑状态 + 追加 memory 进展日志。
5. **走 CI**：ruff + mypy + pytest 全绿。

---

## Part 4 — 关键约束（不可违反）

1. **规模克制、核心够好**：不铺多 Agent 花活、不铺五外壳；核心（识别准+解析透+契约好+可验证）做到位。
2. **混合架构，不纯 LLM**：解析用传统工具做主力，LLM 只做判断/路由/纠错（成本与速度）。
3. **不做重复造轮子**：摄取借鉴 Docling/MinerU 做主力，自研保真做增量；差异化在「多 Agent 编排 + 摄取保真」。
4. **契约即真相**：一切 Agent 通信、适配器转换，都基于 `schemas.py` 的 Document/Chunk。
