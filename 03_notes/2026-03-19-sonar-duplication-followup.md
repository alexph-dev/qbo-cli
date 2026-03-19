# 2026-03-19 sonar duplication followup

- Scope: clear remaining SonarCloud failure after `fix: clear remote quality gates`.
- Remote status found:
  - `Lint`: passed
  - `Tests`: passed
  - `SonarCloud`: failed on `6.2% Duplication on New Code` with duplicated block in `tests/test_commands.py`
- Fix:
  - refactored repeated `gl-report` JSON mocked setup into shared helper inside `TestCmdGlReport`
  - kept coverage for customer path, global format path, and list-account JSON paths
- Verification:
  - `uv run ruff format --check qbo_cli/ tests/test_commands.py tests/test_live.py`
  - `uv run mypy qbo_cli/cli.py tests`
  - `uv run pytest tests/test_commands.py -q`
  - `uv run pytest -q`
