# 统一命令入口：make lint / make test / make check / make fmt
.PHONY: lint typecheck test check fmt install

install:
	uv sync --all-groups
	pre-commit install

lint:
	uv run ruff check .

typecheck:
	uv run mypy pke

test:
	uv run pytest --cov=pke --cov-report=term-missing

check: lint typecheck test

fmt:
	uv run ruff check --fix .
	uv run ruff format .
