# Repository Guidelines

## Project Structure & Module Organization

This Python 3.12+ project uses a `src` layout. Application code is in
`src/hello_coin/`; `cli.py` exposes the `hello-coin` command. Keep each domain
layer self-contained: `ingestion/` normalizes whale-data adapters,
`technical/` fetches and scores market indicators, `liquidation/` handles
heatmap signals, and `decision/` combines signals with the LLM. Each layer
typically contains `models.py`, `service.py`, `storage.py`, and `scheduler.py`.
Source-specific integrations belong in `ingestion/adapters/`. Tests mirror this
layout under `tests/` (for example, `tests/technical/test_indicators.py`).
Design and implementation notes live in `docs/superpowers/`.

## Build, Test, and Development Commands

- `uv sync` installs and locks the project and development dependencies.
- `uv run hello-coin` runs the CLI; use a focused command such as
  `uv run hello-coin technical test BTCUSDT` to check one signal.
- `uv run pytest` runs the normal test suite; it excludes network tests.
- `uv run pytest -m network` runs tests that call real external APIs.
- `uv run ruff check .` lints the codebase.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, and idiomatic Python. Ruff is
the formatter/linter authority; its configured line limit is 100 characters
and target is Python 3.12. Use `snake_case` for modules, functions, variables,
and test files; use `PascalCase` for classes and Pydantic models. Keep pure
calculations in focused modules (for example, `indicators.py` or `score.py`)
and isolate HTTP, configuration, and SQLite access in their respective layers.

## Testing Guidelines

Write pytest tests next to the matching domain path, named
`test_<behavior>.py` with functions such as `test_rsi_returns_none_without_history`.
Mock HTTP clients for ordinary tests; mark tests that make real requests with
`@pytest.mark.network`. Preserve the default offline suite and add regression
coverage for behavior changes. Async tests run automatically via pytest-asyncio.

## Commit & Pull Request Guidelines

Recent history uses concise Conventional Commit-style subjects, for example
`feat: add liquidation CLI commands` and `docs: document the liquidation heatmap integration`.
Use a focused imperative subject with an appropriate prefix (`feat`, `fix`,
`docs`, `test`, or `refactor`). Pull requests should explain the affected
layer, validation performed, any configuration or schema impact, and link the
relevant issue. Include CLI output or screenshots when they clarify a user-visible change.

## Security & Configuration

Put credentials in `.env`; never commit API keys or generated SQLite files in
`data/`. Treat paid and external-data adapters as optional, and avoid running
network tests or live decision commands unless their cost and credentials are
intentional.
