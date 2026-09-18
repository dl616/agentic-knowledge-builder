# 落地计划任务表：从「知识库系统」到「智能测试设计系统」

> **背景**：项目已重新定位为「基于 LLM（大语言模型）的智能测试设计与知识工程系统」，
> 彼时仓库代码仍是「多 Agent（智能体）知识构建平台」——测试领域的那一整层尚未落地，
> 本表把「文档上写了但代码里没有」的部分拆成可执行、可验收的任务。
>
> **现状（v0.2.0）**：S0–S7 **全部完成**并已发布，测试域整层已落地，`pke/testing/` 共 10 个模块。
> 本表保留作为**落地过程记录 + 简历口径 ↔ 代码对照表**，不再代表未完成项。

---

## 一、现状盘点

### 已实现（可直接复用的底座）

| 能力 | 位置 | 状态 |
|---|---|---|
| Agent（智能体）契约（输入 AgentMessage → 输出 AgentMessage，纯函数式） | `pke/agents/base.py` | ✅ 可复用 |
| Compile（编译沉淀）层 WikiStore（归档 + index + log + lint） | `pke/knowledge/compile.py` | ✅ 可改造 |
| RAG（检索增强生成，BM25Plus 关键词检索） | `pke/knowledge/rag.py` | ✅ 可复用 |
| Router（路由，冷热分层 + Wiki 优先 RAG 兜底） | `pke/knowledge/router.py` | ✅ 可复用 |
| 数据契约 Document / Chunk | `pke/schemas.py` | ✅ 可扩展 |
| 摄取 / 质检 / 索引 / 检索 / 问答 五 Agent | `pke/agents/` | ✅ 已跑通 |

### 曾未落实 → 现已落地

| 缺口 | 文档口径 | 落地位置 |
|---|---|---|
| LangGraph（图编排框架）编排 | 「基于 LangGraph 编排四角色」 | ✅ `pke/testing/graph.py`（含无图线性降级） |
| Playwright（浏览器自动化框架） | 「采集 DOM / Accessibility Tree」 | ✅ `pke/testing/explorer.py` |
| Explorer（探索器） | 浏览器探索采集 | ✅ `pke/testing/explorer.py` |
| Analyzer（分析器） | 构建 PageModel（页面对象模型） | ✅ `pke/testing/analyzer.py` |
| CaseGenerator（用例生成器） | 生成结构化用例 | ✅ `pke/testing/generator.py` |
| FailureAnalyzer（失败归因器） | 区分元素失效 / 业务变更 | ✅ `pke/testing/failure.py` |
| 测试资产 Schema（结构化定义） | PageModel / 业务动作 / 测试模式 | ✅ `pke/testing/schemas.py` |
| 用例执行器 | Playwright 跑用例 | ✅ `pke/testing/executor.py`（含定位自愈 + 语义重绑） |
| 语义槽位（跨版本复用关键） | semantic_id | ✅ `pke/testing/semantics.py` |
| 测试知识层（沉淀 + 召回 + 重绑） | Compile 热层 + RAG 冷层 | ✅ `pke/testing/knowledge.py` |

---

## 二、关键设计决策（先定，避免返工）

### 决策 1：无 LLM 也能跑通最小闭环（重要）

LLM（大语言模型）接入是长期硬阻塞（需 API key 或 Ollama）。**不能让它卡死整条线**，因此：

- **Explorer / Analyzer / 执行器 / FailureAnalyzer**：纯规则实现，**不依赖 LLM 即可跑通**。
- **CaseGenerator**：先做「规则模板生成」保证能跑通；LLM 作为**可插拔增强**（有则用智能生成，无则退回模板）。
- 这样任何时候都有可演示、可验证的闭环。

### 决策 2：复用知识层，不另起炉灶

测试资产（PageModel / 业务动作 / 测试模式 / 历史用例）**沿用现有 Compile + RAG + Router 三层**：

- 稳定 PageModel、常用测试模式 → Compile（热层，编译沉淀）
- 长尾历史用例、罕见异常 → RAG（冷层，按需检索）
- CaseGenerator 生成时：先查 Compile 拿模板，再用 RAG 召回历史实例

### 决策 3：验证用「已知内容样本断言法」

沿用项目既有验证传统（见 `docs/DEVELOPMENT.md`）：**先造内容已知的测试样本，断言结果对不对**，
不靠肉眼看。即造一个本地 HTML 登录/注册页 fixture（已知有几个控件），断言 Explorer 抓到的
控件数量与类型正确。

---

## 三、分阶段任务表

### S0 · 收口现状（0.5 天）

| 项 | 内容 | 验收 |
|---|---|---|
| S0-1 | 提交现有未提交代码（orchestrator / quality / router + 三个测试文件） | `git status` 干净 |
| S0-2 | 新增依赖 `playwright`（浏览器自动化）、`langgraph`（图编排）到 pyproject.toml | `uv sync` 通过 |
| S0-3 | 安装 Playwright 浏览器内核 | `playwright install chromium` 成功 |

### S1 · Explorer 探索采集（1 天，不依赖 LLM）

| 项 | 内容 | 验收 |
|---|---|---|
| S1-1 | 定义 `PageSnapshot`（页面快照）数据契约：DOM 结构 + A11y Tree + 操作轨迹 + 元数据 | 契约文件 + 单测 |
| S1-2 | 实现 ExplorerAgent：Playwright 打开种子 URL（链接），抓 DOM（文档对象模型）+ Accessibility Tree（无障碍树） | 能对本地 fixture 页抓到控件 |
| S1-3 | 采集操作轨迹（点击/输入后页面状态变化） | 轨迹可记录 |
| S1-4 | 造本地 HTML 登录页 fixture（已知：手机号框 / 验证码框 / 获取验证码按钮 / 密码框 / 协议勾选 / 注册按钮） | fixture 文件 |
| S1-5 | 单测：断言抓到 6 个控件、类型正确、A11y Tree 结构完整 | `pytest` 全绿 |

### S2 · Analyzer + PageModel（1 天，规则为主）

| 项 | 内容 | 验收 |
|---|---|---|
| S2-1 | 定义 `PageModel` 数据契约（页面用途 + 控件列表 + 业务动作） | 契约文件 |
| S2-2 | 实现 AnalyzerAgent：控件识别（输入框/按钮/下拉/勾选框）+ 去噪（广告、装饰元素） | 能从快照提炼 PageModel |
| S2-3 | 控件 → 业务动作关联（这个按钮是「提交注册」还是「取消」） | 关联正确 |
| S2-4 | 单测：对 fixture 页断言识别出 6 个控件并正确归类 | `pytest` 全绿 |

### S3 · CaseGenerator + 用例生成（1.5 天，先规则后 LLM）

| 项 | 内容 | 验收 |
|---|---|---|
| S3-1 | 定义 `TestCase` 数据契约（步骤 + 断言 + 预期结果 + 优先级） | 契约文件 |
| S3-2 | 定义 `TestPattern`（测试模式）：表单校验 / 边界值 / 权限 / 异常流程 | 模式库 |
| S3-3 | 规则模板生成（无 LLM 可跑）：按控件类型套模式生成用例 | 能对 fixture 页生成用例 |
| S3-4 | LLM 可插拔接口（有 key 则智能生成，无则退回模板） | 接口 + 降级逻辑 |
| S3-5 | 单测：断言生成用例覆盖正常 + 异常（手机号格式 / 验证码 / 密码强度 / 未勾选协议） | `pytest` 全绿 |

### S4 · 执行器 + FailureAnalyzer（1.5 天）

| 项 | 内容 | 验收 |
|---|---|---|
| S4-1 | 实现执行器：把 TestCase 转成 Playwright 操作并跑 | 能对 fixture 页执行 |
| S4-2 | 定义 `FailureReport`（失败报告）契约 | 契约文件 |
| S4-3 | 实现 FailureAnalyzerAgent：分流「元素失效」vs「业务变更」 | 分流逻辑 |
| S4-4 | 元素失效 → 交给 Playwright 定位器自愈（getByRole / getByText 多策略重试） | 自愈生效 |
| S4-5 | 单测（关键）：故意改坏定位器 → 断言判为元素失效；故意改业务规则 → 断言判为业务变更 | `pytest` 全绿 |

### S5 · 测试知识层对接（1 天）

| 项 | 内容 | 验收 |
|---|---|---|
| S5-1 | 扩展 WikiStore 支持测试资产目录（pagemodel / action / pattern / case） | 目录 + 归档 |
| S5-2 | 跑通用例 + PageModel 沉淀进 Compile（热层） | 沉淀生效 |
| S5-3 | 历史用例索引进 RAG（冷层），CaseGenerator 可召回 | 召回生效 |
| S5-4 | 闭环验证：跑第二遍时能召回第一遍的资产，用例数/质量提升 | 对比前后 |

### S6 · LangGraph 编排升级（1 天）

| 项 | 内容 | 验收 |
|---|---|---|
| S6-1 | 引入 LangGraph StateGraph（状态图），替换自研 Orchestrator 流水线 | 图可跑通 |
| S6-2 | 编排四角色：Explorer → Analyzer → CaseGenerator → （执行）→ FailureAnalyzer | 节点状态可观测 |
| S6-3 | 支持分支/回退：探索失败回退重探；用例生成失败回 Analyzer 补 PageModel | 回退生效 |
| S6-4 | 单测：断言图按预期顺序流转 + 异常分支正确 | `pytest` 全绿 |

### S7 · 端到端闭环 + 演示（1 天）

| 项 | 内容 | 验收 |
|---|---|---|
| S7-1 | 一键脚本：种子 URL → 探索 → 建模 → 生成用例 → 执行 → 归因 → 沉淀 | 一行命令跑通 |
| S7-2 | 完整 demo：登录页全流程演示 + 输出用例清单 | demo 可复现 |
| S7-3 | 更新 README / 文档，让简历口径与代码对上 | 文档一致 |
| S7-4 | 全量回归：ruff + mypy + pytest 全绿 | CI 通过 |

---

## 四、进度总览

| 阶段 | 内容 | 依赖 LLM | 估时 | 状态 |
|---|---|---|---|---|
| S0 | 收口现状 + 依赖 | 否 | 0.5 天 | ✅ 完成（v0.2.0 已发布 + tag） |
| S1 | Explorer 探索采集 | 否 | 1 天 | ✅ 完成 |
| S2 | Analyzer + PageModel | 否 | 1 天 | ✅ 完成 |
| S3 | CaseGenerator 用例生成 | 可选 | 1.5 天 | ✅ 完成（规则版；LLM 接口已留） |
| S4 | 执行器 + FailureAnalyzer | 否 | 1.5 天 | ✅ 完成 |
| S5 | 测试知识层对接 | 否 | 1 天 | ✅ 完成（含跨版本语义重绑） |
| S6 | LangGraph 编排 | 否 | 1 天 | ✅ 完成（含无图降级） |
| S7 | 端到端闭环 + demo | 可选 | 1 天 | ✅ 完成（三轮 E2E + 文档对齐 + 全绿） |

**合计约 8.5 天**；前 4 个阶段（S0–S4）跑完即有「可演示的最小闭环」，约 4.5 天。

**S7 验收结果（真实无头 Chromium，三轮端到端）**

| 轮次 | 场景 | 结果 |
|---|---|---|
| v1 | 基线注册页冷启动 | 10/10 通过 |
| v2 | 去 label 改版页，复用 v1 沉淀的 5 条历史用例 | 10/10 通过，3 处语义重绑（phone「手机号」→「请输入手机号」、code、password） |
| v3 | 成功文案变更页 | 8/10，2 条判「业务变更」挂人工 |

门禁：`ruff` ✅ / `mypy` 0 issue ✅ / `pytest` 212 项全绿 ✅

---

## 四之二、已落地代码清单（简历口径 ↔ 代码对照）

| 能力 | 代码位置 | 验证 |
|---|---|---|
| Explorer（探索器）：Playwright 抓 DOM + 可见性过滤 + 控件命名 | `pke/testing/explorer.py` | 单元 + 真实浏览器集成 |
| Analyzer（分析器）：控件归类 + 去噪 + 业务动作关联 → PageModel | `pke/testing/analyzer.py` | 单元 |
| CaseGenerator（用例生成器）：正常 / 异常 / 边界三类模式 | `pke/testing/generator.py` | 单元 |
| 语义层（semantic_id 语义槽位 + 字段规则） | `pke/testing/semantics.py` | 单元 |
| 执行器 + 定位器自愈（多策略回退） | `pke/testing/executor.py` | 真实浏览器集成 |
| FailureAnalyzer（失败归因）：元素失效 vs 业务变更 | `pke/testing/failure.py` | 单元 + 集成 |
| 测试知识层（沉淀 Wiki + 召回 RAG + 语义重绑） | `pke/testing/knowledge.py` | 单元 + 跨版本集成 |
| 编排层（LangGraph StateGraph + 线性降级） | `pke/testing/graph.py` | 单元（两条路径同结果） |
| 一键演示 | `scripts/demo_pipeline.py` | 两轮闭环可复现 |

**当前唯一硬阻塞**：LLM 真实调用（knot 平台网关需 iOA/TOF 登录，Bearer 穿不透）。
所有不依赖 LLM 的环节均已跑通，LLM 为可插拔增强——有则智能生成，无则规则模板。

---

## 五、风险与阻塞

| 风险 | 影响 | 应对 |
|---|---|---|
| LLM 接入未定（API key / Ollama） | 影响 S3 智能生成、S7 演示质量 | ✅ 已闭环：knot 网关（iOA/TOF）Bearer 穿不透 → 走规则模板，S3/S7 均验收通过；`pke/llm.py` 留有可插拔接口，换通道即可升级 |
| Playwright 浏览器内核下载慢/失败 | 阻塞 S1 | 优先用本地 HTML fixture，不依赖外网页面 |
| 目标站点有反爬/登录墙 | 影响真实页面采集 | 先用本地 fixture 验证，真实站点后补 |
| 一次铺太大导致返工 | 整体风险 | 严格按 S0→S7 顺序，每阶段验收通过再进下一阶段 |
