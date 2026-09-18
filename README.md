# Agentic Knowledge Builder

[![CI](https://github.com/dl616/agentic-knowledge-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/dl616/agentic-knowledge-builder/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> **基于 LLM（大语言模型）的智能测试设计与知识工程系统。**
> 给一个页面地址，四个 Agent（智能体）自动走完「探索 → 建模 → 生成用例 → 执行 → 失败归因 → 沉淀复用」；
> 测试人员只做「审核 + 编排」，用例资产像知识一样越用越厚。

---

## 一句话

**用多 Agent 编排，把 Web 功能测试的「用例设计 + 执行验证 + 资产沉淀」全流程自动化。**

---

## 解决什么问题

三个测试同学每天都在扛、但工具没解决的问题：

1. **用例靠人堆，改版即返工**：页面一改版，控件名/结构变了，历史用例全废，重写一遍。
2. **自动化脚本脆**：脚本绑死在 XPath / CSS Selector（选择器）上，前端改个 class 就大面积红了。
3. **失败原因分不清**：一次跑挂 30 条，到底是「元素失效」（脚本问题，能自愈）还是「业务真变了」（要人工确认）？全靠人一条条看。

对应的设计：

| 问题 | 我们的做法 |
|---|---|
| 改版即返工 | 给控件打**语义槽位**（semantic_id，如 phone / code / agreement），用例绑语义不绑字面名 |
| 脚本脆 | 执行器**多策略定位自愈**：id → name → placeholder → role → text 逐级回退 |
| 失败分不清 | FailureAnalyzer（失败归因器）分流「元素失效 / 业务变更」，只把后者推给人工 |

---

## 核心流程（一条流水线七个节点）

```
explore   探索  Playwright 打开页面，抓 DOM + 可见性过滤 + 控件命名
analyze   建模  控件归类 + 去噪 + 业务动作关联 → PageModel（页面对象模型）
recall    召回  从知识库取可复用的历史用例，按语义槽位**重绑**到当前页面
generate  生成  正常 / 异常 / 边界三类模式 → 结构化 TestCase
execute   执行  真实浏览器跑一遍，定位失败自动多策略自愈
attribute 归因  失败分流：元素失效（自愈） vs 业务变更（人工确认）
compile   沉淀  通过的用例 + PageModel 回写知识层（Wiki 热层 + RAG 冷层）
```

编排层用 LangGraph StateGraph（状态图）实现，节点之间靠**共享状态**通信；
装不上 LangGraph 时自动降级为**同顺序线性执行**，功能一致——这是全项目通则：**外部依赖不能让主线停工**。

---

## 多 Agent 团队

**测试域（本次主线）**

```
TestPipeline 编排（LangGraph 状态图）
   ├─ Explorer         探索器：页面快照采集
   ├─ Analyzer         分析器：快照 → PageModel + 业务动作
   ├─ TestKnowledge    知识层：历史资产召回 + 语义重绑
   ├─ CaseGenerator    用例生成器：规则模板（LLM 可插拔增强）
   ├─ CaseExecutor     执行器：真实浏览器执行 + 定位自愈
   └─ FailureAnalyzer  归因器：元素失效 / 业务变更 分流
```

**知识层（底座，已跑通）**

```
Orchestrator 总控（识别 · 规划 · 调度）
   ├─ Ingest 摄取（分类 · 解析 · 录入保真）
   ├─ Quality 质检（校验丢字/乱码，纠错重试）
   ├─ Index 索引（分块 · 向量化）
   ├─ Retrieval 检索（混合检索 · 重排）
   └─ Answer 问答（带引用生成）
```

两条流水线在「沉淀」这一步交汇：测试资产通过知识层的 Compile / RAG 入库、被下一轮召回。

---

## 三层混合知识架构（查存互补）

- **Compile 层（LLM-Wiki，编译沉淀）**：稳定的 PageModel、常用测试模式，可综合、越用越厚
- **RAG 层（检索增强生成，BM25Plus）**：长尾历史用例、罕见异常，查询时按需检索、全量可溯源
- **Memory 层**：用户偏好与过往会话

互补机制：**冷热分层**（核心进 Wiki、长尾走检索）+ **Wiki 优先 RAG 兜底** + **编译回流**。

---

## 快速开始

```bash
# 1. 建环境 + 装依赖（含 playwright / langgraph）
uv sync
uv run playwright install chromium

# 2. 一键演示：对一个本地注册页跑完整闭环
uv run python scripts/demo_pipeline.py --execute

# 3. 两轮闭环：第二轮换改版页，看历史用例被复用 + 语义重绑
uv run python scripts/demo_pipeline.py tests/fixtures/signup.html --execute \
    --next-url tests/fixtures/signup_v2_relayout.html

# 4. 走编排层（LangGraph）并输出报告
uv run python scripts/demo_pipeline.py tests/fixtures/signup.html --graph
```

> LLM（大语言模型）为**可插拔增强**：配了 key 就智能生成，没配就走规则模板，闭环照样跑通。

---

## 目录结构

```
pke/
├── testing/         # 测试域（主线）
│   ├── explorer.py    # 探索采集
│   ├── analyzer.py    # 页面建模
│   ├── semantics.py   # 语义槽位 + 字段规则（跨版本复用的关键）
│   ├── generator.py   # 用例生成
│   ├── executor.py    # 执行 + 定位自愈 + 跨版本重绑
│   ├── failure.py     # 失败归因分流
│   ├── knowledge.py   # 测试知识层（Compile + RAG 桥接）
│   └── graph.py       # LangGraph 编排 + 线性降级
├── agents/          # 知识层 Agent：orchestrator + ingest/quality/index/retrieval/answer
├── knowledge/       # 三层知识：compile(LLM-Wiki) / rag / router
├── schemas.py       # 数据契约：Document / Chunk（唯一真相）
└── config.py        # 配置
tests/               # unit / integration（真实浏览器）/ fixtures（已知内容样本）
docs/                # PRD（做什么）+ DEVELOPMENT（怎么做）+ 项目讲述
```

---

## 验证方式

沿用项目传统 **「已知内容样本断言法」**（见 `docs/DEVELOPMENT.md`）：先造内容已知的样本，断言结果，不靠肉眼看。

- `tests/fixtures/signup.html` — 基线注册页（已知 6 个控件）
- `tests/fixtures/signup_v2_relayout.html` — 改版页：去掉 label，验证**跨版本复用**
- `tests/fixtures/signup_v3_business_change.html` — 业务变更页：成功文案改了，验证**归因分流**

```bash
uv run pytest tests/unit -q          # 单元
uv run pytest tests/integration -q   # 真实浏览器集成
uv run ruff check pke scripts tests && uv run mypy pke
```

---

## 实测数据（v0.2.0，真实无头 Chromium）

三轮端到端，跑的是上面三个 fixture：

| 轮次 | 场景 | 结果 |
|---|---|---|
| v1 | 基线注册页，冷启动 | **10/10 通过** |
| v2 | 去掉 label 的改版页，复用 v1 沉淀的 5 条历史用例 | **10/10 通过**，3 处语义重绑（phone「手机号」→「请输入手机号」、code、password） |
| v3 | 成功文案变更页 | **8/10**，2 条判「业务变更」挂人工（归因：未出现「注册成功」，实际为「注册申请已提交，请查收激活邮件」） |

也就是说：改版后历史用例**没有一条重写**，靠语义槽位自动重绑；真·业务变更被准确挑出来交给人判断，而不是伪装成脚本报错。

质量门禁：`ruff` ✅ / `mypy` 0 issue ✅ / `pytest` **212 项全绿** ✅（含真实浏览器集成）

---

## 当前状态

- **v0.2.0 已发布**（含 tag），变更见 [`CHANGELOG.md`](CHANGELOG.md)。
- **唯一硬阻塞**：LLM 真实调用。内部 knot 平台走 iOA/TOF 登录网关，Bearer 穿不透。
  因此当前全部能力走**规则模板 + 可插拔接口**——这是有意为之的设计决策，不是半成品：
  配好任意 LLM 通道（`pke/llm.py`）后，用例生成与归因自动升级为智能模式，主线流程无需改动。

---

## 文档

- [`CHANGELOG.md`](CHANGELOG.md) — 版本变更
- [`docs/PROJECT-NARRATIVE.md`](docs/PROJECT-NARRATIVE.md) — 项目讲述（面试/汇报口径，含全流程口述脚本与实测数据）
- [`docs/IMPLEMENTATION-PLAN.md`](docs/IMPLEMENTATION-PLAN.md) — 落地计划任务表与代码对照（S0–S7 全完成）
- [`docs/POSITIONING-V3.md`](docs/POSITIONING-V3.md) — 定位调研
- [`docs/PRD.md`](docs/PRD.md) — 产品需求与定位
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — 开发架构与规范
- [`docs/MASTER_PLAN.md`](docs/MASTER_PLAN.md) — 最终开发方案总纲

## 许可

[MIT](LICENSE)

---

## 定位边界

**是什么**：一个会探索页面、会设计用例、会执行验证、会把经验沉淀成资产的测试 Agent 团队。
**不是什么**：不是又一个录制回放工具，不是又一层 XPath 封装，不是「生成一堆没人看的用例」的玩具。
**差异化**：别人做「脚本生成」（绑死选择器、改版即废），我们做「用例 + 知识闭环」（绑语义槽位、跨版本复用、失败自动归因）。
