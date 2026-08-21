# 贡献指南（Contributing）

感谢你考虑为 Agentic Knowledge Builder 贡献代码。本项目遵循一套明确的工程规范，请先了解再动手。

## 快速上手

```bash
# 1. 克隆 + 装依赖
git clone https://github.com/dl616/agentic-knowledge-builder.git
cd agentic-knowledge-builder
uv sync --all-groups

# 2. 安装 pre-commit 钩子（提交前自动检查）
pre-commit install

# 3. 跑一遍全部检查
make check
```

## 开发流程

1. **从 issue 开始**：有 bug 或想法，先开 issue 讨论，避免重复劳动。
2. **开分支**：`git checkout -b feat/你的功能` 或 `fix/你的修复`，不要直接在 main 上改。
3. **写代码 + 测试**：每个功能/修复都要配单元测试（见下方「测试规范」）。
4. **提交**：遵循 [Conventional Commits](https://www.conventionalcommits.org/)——`feat:` / `fix:` / `docs:` / `test:` / `refactor:` / `chore:`。
5. **开 PR**：描述清楚「改了什么、为什么」，关联相关 issue。

## 代码规范

本项目用 **ruff** 做格式化和 lint、**mypy** 做类型检查，全部配置在 `pyproject.toml`。提交前跑：

```bash
make lint        # ruff check
make typecheck   # mypy
make test        # pytest
# 或一键全跑
make check
```

关键约定：
- **全量类型注解**，`from __future__ import annotations`。
- 公共函数必须有 docstring（一句话说明 + 关键坑）。
- 注释解释「为什么」，不解释「是什么」。
- 裸 `except`、散落魔法值、硬编码路径一律禁止。

## 测试规范

- 框架 pytest，覆盖率门槛 **85%**。
- **核心方法论：已知样本断言**——不靠肉眼，先造「内容已知」的测试样本，再断言提取/检索结果逐项正确。
- 测试目录：`tests/unit/`（单元）、`tests/integration/`（集成）、`tests/fixtures/`（样本）。

## 架构约定（改动前必读）

- **数据契约即真相**：所有 Agent 通过 `pke/schemas.py` 的 `Document`/`Chunk` 通信，改契约要改版本号。
- **Agent 是纯函数**：输入 `AgentMessage` 输出 `AgentMessage`，Agent 间不直接互相调用，统一由 Orchestrator 调度。
- **规模克制**：不要过早铺大摊子，先跑通最小闭环，再按里程碑迭代。

详见 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。

## 行为准则

- 尊重他人，就事论事。
- 讨论聚焦技术，不做人身攻击。
- 帮助新贡献者，善待提问。
