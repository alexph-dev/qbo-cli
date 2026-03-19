# 2026-03-19 gl guardrails followup

- Scope: tighten `gl-report` test coverage after remote-gate fixes were green.
- Added coverage for:
  - global `-f json` path reaching `cmd_gl_report`
  - `--list-accounts` JSON via both subcommand output and global format
  - explicit reject paths for unsupported `txns` / `expanded` / global `tsv`
- Refactor:
  - centralized repeated `gl-report` test arg setup in helper methods
- Verification:
  - `uv run ruff check qbo_cli/ tests/test_commands.py tests/test_live.py README.md 02_docs/architecture.md`
  - `uv run ruff format --check qbo_cli/ tests/test_commands.py tests/test_live.py`
  - `uv run mypy qbo_cli/cli.py tests`
  - `uv run pytest -q`
  - `uv run pytest -m live -q`
