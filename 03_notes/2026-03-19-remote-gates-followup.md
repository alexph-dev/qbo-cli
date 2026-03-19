# 2026-03-19 remote gates followup

- Scope: clear remote GitHub failures after `fix: honor gl-report format flags`.
- Remote status found:
  - `Tests`: passed
  - `Lint`: failed on `ruff format --check qbo_cli/`
  - `SonarCloud`: failed quality gate on 2 new float-equality issues in `tests/test_commands.py`
- Fixes:
  - ran Ruff formatter on `qbo_cli/cli.py`
  - replaced exact float assertions with `pytest.approx`
  - fixed sibling format-contract bug for `gl-report --list-accounts`
  - added unit + live coverage for JSON list-account paths
- Verification:
  - `uv run ruff check qbo_cli/ tests/test_commands.py tests/test_live.py README.md 02_docs/architecture.md`
  - `uv run ruff format --check qbo_cli/ tests/test_commands.py tests/test_live.py`
  - `uv run mypy qbo_cli/cli.py tests`
  - `uv run pytest -q`
  - `uv run pytest -m live -q`
