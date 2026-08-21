# Agentic Knowledge Builder

[![CI](https://github.com/dl616/agentic-knowledge-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/dl616/agentic-knowledge-builder/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> 多 Agent 协作、查存混合的企业级知识库构建平台。
> 丢一堆杂乱文档进来，一个总控 Agent 调度五个专项 Agent，自动构建出「能查、能问、答案有出处、知识越用越厚」的知识库。

---

## 一句话

**用多 Agent 编排，把一个企业知识库的「构建 + 查询 + 沉淀」全流程自动化、协作化。**

---

## 解决什么问题

三个正在发生的、真实的问题：

1. **摄取是 RAG 的真正瓶颈**：模型再好，喂进去的文档是坏的（排版乱、代码缩进毁、公式丢、表格散），答案就是错的——「垃圾进，垃圾出」。
2. **纯检索（RAG）不沉淀**：每次查询从零检索，知识不积累、无法跨文档综合。
3. **纯编译（LLM-Wiki）不规模化**：Karpathy 本人划界——LLM Wiki 只适合「个人 + 100~200 篇稳定语料」，量大了必须回到检索层。

---

## 三大核心设计

| 支柱 | 定位 |
|---|---|
| **多 Agent 编排** | 核心。6 角色 Agent 团队，LangGraph 编排，把知识库构建过程协作化、自动化 |
| **摄取保真** | 特色。识别 + 解析 + 清洗，代码缩进 / 表格 / 公式 / 符号不丢 |
| **三层混合知识** | 企业级关键。Compile 编译沉淀 + RAG 实时检索 + Memory 用户记忆，取长补短 |

---

## 多 Agent 团队

```
Orchestrator 总控（识别 · 规划 · 调度）
   ├─ Ingest 摄取（分类 · 解析 · 录入保真）
   ├─ Quality 质检（校验丢字/乱码，纠错重试）
   ├─ Index 索引（分块 · 向量化）
   ├─ Retrieval 检索（混合检索 · 重排）
   └─ Answer 问答（带引用生成）
```

## 三层混合知识架构（查存互补）

- **Compile 层（LLM-Wiki）**：核心稳定知识，摄取时编译沉淀，可综合、越用越厚
- **RAG 层（向量库）**：长尾海量文档，查询时实时检索，全量可溯源
- **Memory 层**：用户偏好与过往会话

互补机制：**冷热分层**（核心进 Wiki、长尾走向量库）+ **Wiki 优先 RAG 兜底** + **编译回流**（RAG 高频片段回流编译进 Wiki）。

---

## 快速开始

```bash
# 1. 建环境 + 装依赖
uv sync

# 2. 生成「已知内容」的测试 PDF（验证录入对不对）
uv run python scripts/make_sample_pdf.py

# 3. 摄取它，看识别 + 结构化结果
uv run python scripts/ingest.py data/raw/sample.pdf
```

---

## 目录结构

```
pke/
├── agents/          # Agent 层：orchestrator + ingest/quality/index/retrieval/answer
├── knowledge/       # 三层知识：compile(LLM-Wiki) / rag / memory / router
├── adapters/        # 输出适配器：中间格式 → JSON/Markdown/文本
├── schemas.py       # 数据契约：Document / Chunk（唯一真相）
├── scanner.py       # 识别器
└── config.py        # 配置
tests/               # unit / integration / fixtures
docs/                # PRD（做什么）+ DEVELOPMENT（怎么做）
```

---

## 文档

- [`docs/PRD.md`](docs/PRD.md) — 产品需求与定位（做什么）
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — 开发架构与规范（怎么做）
- [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) — 最终开发方案总纲
- [`docs/REVIEW.md`](docs/REVIEW.md) — 全面审查报告
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 贡献指南
- [`CHANGELOG.md`](CHANGELOG.md) — 变更日志

## 许可

[MIT](LICENSE)

---

## 定位边界

**是什么**：一个多 Agent 协作的 RAG 知识构建引擎，处在「杂乱文档 → 可用知识库」这一段。
**不是什么**：不是又一个笔记软件，不是又一个单解析库，不是 RAG 的「又一个 demo」。
**差异化**：别人做「一条流水线」或「单层检索」，我们做「一个会分工、会质检、会沉淀、查存互补的 Agent 团队」。
