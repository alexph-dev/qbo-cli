# 2026-03-19 gl-format review merge

- Scope: review local refactor work, verify merge readiness, push `main`.
- Finding: `gl-report` did not honor shared format resolution for global `-f json` and did not accept
  subcommand `--format json`.
- Fix: route `gl-report` through `_resolve_fmt()`, add `--format` alias, reject unsupported `tsv`
  explicitly, add parser/handler coverage, update docs.
- Verification:
  - `uv run ruff check qbo_cli/cli.py tests/test_commands.py tests/test_live.py README.md`
  - `uv run mypy qbo_cli/cli.py tests`
  - `uv run pytest -q`
  - `uv run pytest -m live -q`
- Note: repo-wide Ruff still reports pre-existing unrelated issues already present on `origin/main`
  in untouched test files.
