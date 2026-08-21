# 最终项目开发方案（Master Plan）

> 多 Agent 知识构建平台（Agentic Knowledge Builder）的总纲。
> 本文是唯一入口，整合整改结果 + 补齐的详细规划 + 最小可演示路线。
> 其他文档各司其职：PRD（做什么）、DEVELOPMENT（怎么做）、REVIEW（审查）。

---

## 0. 本次整改结果（已完成）

| 项 | 整改前 | 整改后 |
|---|---|---|
| README | 与 PRD 矛盾（"不追求多 Agent"） | ✅ 已重写对齐 PRD v2.0 |
| akb-dev skill | 自相矛盾（"避免多 Agent 花活"） | ✅ 已修正边界表述 |
| git 仓库 | 未初始化 | ✅ 已 `git init` |
| 依赖管理 | 手写 requirements.txt | ✅ 已补 `pyproject.toml`（uv） |
| .gitignore | 缺失 | ✅ 已补 |
| 目录结构 | 旧结构 + 4 个空壳目录 | ✅ 已迁移对齐 DEVELOPMENT.md |
| 测试 | 零测试 | ✅ 13 个单测全绿（schemas/scanner/pdf/text） |
| PRD 缺口 | 缺验证/成本/安全/演示子集 | ✅ 已补 4 节 |

---

## 1. 项目全貌（定稿）

- **定位**：多 Agent 协作、查存混合的企业级知识库构建平台。
- **核心**：多 Agent 编排（LangGraph）——Orchestrator 总控 + Ingest/Quality/Index/Retrieval/Answer 五专项。
- **特色**：摄取保真（代码缩进/表格/公式/符号不丢）。
- **知识架构**：三层混合——Compile(LLM-Wiki 编译沉淀) + RAG(向量检索) + Memory(用户记忆)，配路由 + 编译回流。
- **技术栈**：LangGraph / Docling·MinerU·PyMuPDF / Qdrant / 混合检索 / 可插拔模型 / FastAPI / pytest+RAGAs。

---

## 2. 盘查发现的规划缺口 + 补齐方案

审查时确认了「规划跑得快、代码跟不上」，整改后还发现以下**规划本身不够详细**的地方，本节逐一补齐：

### 2.1 各 Agent 的输入输出契约（原来只有抽象接口，缺具体定义）

| Agent | 输入（AgentMessage.payload） | 输出（AgentMessage.payload） |
|---|---|---|
| Orchestrator | 任务描述 + 文件列表 | 规划结果 + 调度的 Agent 序列 |
| Ingest | 文件路径 | `Document`（见 schemas） |
| Quality | `Document` | `Document` + `quality_report`（丢字/乱码/残缺清单） |
| Index | `Document` | 索引写入结果（chunk 数、向量 id 列表） |
| Retrieval | 查询字符串 | 相关 `Chunk[]`（带出处 + 得分） |
| Answer | 查询 + `Chunk[]` | 答案 + 引用标注 `[1][2]` |

**规范**：每个 Agent 的 `run()` 签名统一，`meta` 里带 `agent`、`step`、`confidence` 字段供质检与观测。

### 2.2 数据模型全集（原来只有 Document/Chunk，缺其余）

```python
# schemas.py 已有
Document / Chunk

# 待补（按里程碑逐步加入）
WikiPage     # Compile 层产物：frontmatter + 正文 + [[双向链接]] + 引用
MemoryEntry  # Memory 层：用户偏好/事实，带 scope(user/agent/global)
RouteDecision# 路由结果：{ target: "compile"|"rag"|"memory", reason, confidence }
QualityReport# 质检报告：{ issues: [{type, location, severity}], passed: bool }
```

**原则**：所有新增数据结构都进 `schemas.py`，统一版本号管理。

### 2.3 Compile 层（LLM-Wiki）具体契约（原来只有"LLM-Wiki 模式"一句话）

```
data/wiki/
├── schema.md      # 结构规则 + 页面类型 + 生命周期（契约文件，LLM 读它）
├── index.md       # 内容目录（编译页面的入口）
├── log.md         # 追加式变更日志
├── entities/      # 实体页（人/组织/产品/技术）
├── concepts/      # 概念页（理论/方法/术语）
└── synthesis/     # 跨源综合分析

三个操作：
  ingest(source) → 读源 → 更新/新建 wiki 页 + 双向链接 + index + log
  query(q)      → 先查 index（缓存命中）→ 再走检索
  lint()        → 检查死链/矛盾/缺口 → 修复 + 记录
```

### 2.4 评测集设计（原来只有"自建评测集"四个字）

- **脏样本集**（`eval/dataset/`）：覆盖 5 类坑——代码缩进 PDF、含表格 PDF、扫描件、含公式 PDF、乱排版网页。
- **标准答案**：每份样本配「预期提取结果」，逐字段标注。
- **指标**：
  - 保真率 = 正确还原的字段数 / 总字段数（代码缩进、表格、公式、符号分项算）
  - 检索命中率 = Top-5 命中 / 查询总数
  - 忠实度 = RAGAs faithfulness（答案是否忠实于检索到的证据）

### 2.5 部署方案（原来完全缺失）

| 阶段 | 部署形态 | 组件 |
|---|---|---|
| 开发期 | 本地 CLI + venv | 无外部依赖 |
| 单机自用 | `uv run` + 本地 Qdrant | 一条命令起 |
| 企业部署 | Docker Compose | pke + Qdrant + PostgreSQL + 可选 Web UI |

---

## 3. 最小可演示路线（优先交付）

目标：**两周内出一个能演示的 demo**，而非等 M0-M7 全走完。

```
阶段 A（本周）：摄取闭环 ✅ 已完成
  scanner 识别 + ingest(PDF/文本) 解析 + 统一 Document → 已验证

阶段 B（下周）：问答闭环
  index(分块+向量，先用轻量 Chroma/SQLite) + retrieval(混合) + answer(带引用)

阶段 C（第三周）：沉淀闭环
  compile(LLM-Wiki 编译) + 一个可交互 CLI 演示
```

**演示脚本**（给人看的一句话）：「把这份脏 PDF 丢进去 → 它认出类型、还原代码缩进、检索到相关内容、带出处回答、并把结论沉淀进 Wiki。」

---

## 4. 分阶段实施计划（对齐里程碑 M0-M7）

| 阶段 | 里程碑 | 关键交付 | 验证 |
|---|---|---|---|
| 已完 | M0 | schemas + scanner + 工程地基 | 13 测试绿 |
| 本周 | M1 | ingest 补网页/图片 | 保真率 |
| | M2 | quality 质检 | 丢字检出率 |
| 下周 | M3 | index + retrieval | 命中率 |
| | M4 | answer 带引用 | RAGAs |
| 第三周 | M5 | compile(LLM-Wiki) | index/log 一致 |
| 之后 | M6/M7 | 路由+回流 / Memory+企业接入 | 端到端 |

---

## 5. 文档索引

| 文档 | 作用 |
|---|---|
| `docs/PRD.md` | 做什么：定位/架构/三层知识/技术栈/里程碑/评测/成本安全 |
| `docs/DEVELOPMENT.md` | 怎么做：目录结构/规范/开发节奏 |
| `docs/REVIEW.md` | 审查报告：发现的问题 + 优先行动 |
| **`docs/MASTER_PLAN.md`（本文）** | **总纲：整改结果 + 补齐规划 + 最终路线** |
| `README.md` | 门面：给人看 |

---

## 6. 一句话

> **方向已定、地基已夯、规划已补齐——接下来是执行期：按「摄取闭环（已完）→ 问答闭环 → 沉淀闭环」三周节奏，交付一个能演示、能评测、能讲故事的 Agentic Knowledge Builder。**
