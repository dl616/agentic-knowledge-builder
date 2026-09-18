# Changelog

本项目遵循 [语义化版本](https://semver.org/) 和 [Keep a Changelog](https://keepachangelog.com/) 规范。

## [Unreleased]

### Added
- 网页摄取器（`pke/agents/ingest/web.py`）：trafilatura 正文抽取，去广告/导航，保留 URL 溯源。
- Markdown/纯文本摄取器（`pke/agents/ingest/text.py`）：按标题/代码块/段落分块，代码缩进保真。

## [0.2.0] - 2026-09-17 —— 测试域：智能测试设计与知识工程

### Added
- 测试域数据契约 `pke/testing/schemas.py`：PageSnapshot / PageModel / Control / TestCase / TestStep / CaseResult / FailureReport。
- Explorer（探索器）`explorer.py`：Playwright 抓 DOM + 可见性过滤 + 控件命名（label > aria > placeholder > 相邻文本）。
- Analyzer（分析器）`analyzer.py`：控件归类 + 去噪 + 业务动作关联 → PageModel。
- 语义层 `semantics.py`：semantic_id 语义槽位 + 字段规则（跨版本复用的关键）。
- CaseGenerator（用例生成器）`generator.py`：正常 / 异常 / 边界三类模式，LLM 可插拔增强。
- 执行器 `executor.py`：真实浏览器执行 + 多策略定位自愈 + 跨版本语义重绑。
- FailureAnalyzer（失败归因器）`failure.py`：元素失效（自愈）vs 业务变更（人工确认）分流。
- 测试知识层 `knowledge.py`：PageModel / 用例沉淀 Wiki（热层），历史用例 RAG（冷层）召回 + 重绑。
- 编排层 `graph.py`：LangGraph StateGraph 七节点流水线，未装 langgraph 时线性降级。
- 一键演示 `scripts/demo_pipeline.py`：支持 `--execute` / `--next-url`（跨版本闭环）/ `--graph`。
- 验证样本：`signup.html` / `signup_v2_relayout.html`（改版）/ `signup_v3_business_change.html`（业务变更）。
- 文档：`docs/PROJECT-NARRATIVE.md`（项目讲述 + 实测数据）、`docs/IMPLEMENTATION-PLAN.md`（落地任务表）。

### Changed
- 文档对齐 v0.2.0：README 新增「实测数据（三轮端到端）」与「当前状态」；IMPLEMENTATION-PLAN 进度全标记完成并补验收结果。

### Fixed
- 控件命名在「无 label」改版页退化为 `on`（补充相邻文本识别，且只对勾选框/单选框生效，避免误取整个表单文本）。
- 历史用例跨版本复用失效（用例 ID 绑字面名 → 改版即断）：改为绑语义槽位，召回时重绑并留痕。
- 拦门类用例断言错误文案在原生 required 校验下必挂：新增 `assert_not_text`（断言不出现成功提示）。
- mypy 在 pydantic 2.13 + mypy 2.3 组合下内部崩溃：配置跳过 langgraph / pydantic 源码。

## [0.1.0] - 2026-08-21

### Added
- 项目骨架：多 Agent 知识构建平台（Agentic Knowledge Builder）。
- 识别器 `scanner.py`：等宽字体检测（代码块）、表格检测、扫描件检测。
- PDF 摄取器：段落重建（软换行合并）、代码块缩进保真、表格结构化、图片抠出、扫描件标记。
- 数据契约 `schemas.py`：Document / Chunk + SCHEMA_VERSION。
- Agent 抽象接口 `agents/base.py`：Agent + AgentMessage。
- 工程地基：pyproject.toml（uv）、ruff、mypy、pytest（15 测试）。
- 文档：PRD / DEVELOPMENT / MASTER_PLAN / REVIEW。

### Fixed
- 代码块被段落重建拍平（等宽字体识别，保留换行缩进）。
- 特殊符号 `²`/`°` 静默丢失（定位为字体字形问题）。

[Unreleased]: https://github.com/dl616/agentic-knowledge-builder/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dl616/agentic-knowledge-builder/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dl616/agentic-knowledge-builder/releases/tag/v0.1.0
