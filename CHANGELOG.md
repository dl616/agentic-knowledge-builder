# Changelog

本项目遵循 [语义化版本](https://semver.org/) 和 [Keep a Changelog](https://keepachangelog.com/) 规范。

## [Unreleased]

### Added
- 网页摄取器（`pke/agents/ingest/web.py`）：trafilatura 正文抽取，去广告/导航，保留 URL 溯源。
- Markdown/纯文本摄取器（`pke/agents/ingest/text.py`）：按标题/代码块/段落分块，代码缩进保真。

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

[Unreleased]: https://github.com/dl616/agentic-knowledge-builder/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dl616/agentic-knowledge-builder/releases/tag/v0.1.0
