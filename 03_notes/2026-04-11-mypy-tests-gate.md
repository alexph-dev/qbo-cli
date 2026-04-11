# 2026-04-11 - Tests mypy gate

Extend strict typing gate to `tests/`. Post-wave 6 follow-up.

## Starting state

`mypy qbo_cli tests` -> 41 errors in 5 files. Source (`qbo_cli`) already clean.

## Error categories

- 24x `call-overload` in `test_live_sandbox_crud.py` -> `qbo_json` declared
  `dict | list`, tests indexed with strings. Retype helper to return `Any` (QBO
  payloads are genuinely dynamic: dict for entity wrappers, list for query
  results). No behaviour change.
- 14x `method-assign` in `tests/conftest.py` + `tests/test_commands.py` ->
  `client.request = MagicMock(...)` pattern. Suppress in place with
  `# type: ignore[method-assign]` (specific code, not blanket).
- 1x `union-attr` in `test_pure.py::test_id_preferred_over_name` -> would need
  a new `assert is not None`, which task rules forbid. Narrow suppression.
- 1x `arg-type` in `test_parsing.py::test_empty_rows` -> test intentionally
  passes `None` to validate defensive branch. Narrow suppression.
- 1x `var-annotated` in `test_parsing.py::test_empty_tree` -> real fix, typed
  `idx: dict[str, GLSection] = {}`.

## pyproject.toml

Added `files = ["qbo_cli", "tests"]` under `[tool.mypy]` so bare `uv run mypy`
covers both. Keeps `mypy qbo_cli tests` working identically.

## Gates

- `uv run mypy qbo_cli tests` -> 0 errors across 24 source files
- `uv run ruff check .` -> clean
- `uv run ruff format --check .` -> 24 files already formatted
- `uv run pytest` -> 177 passed, 29 deselected (live)
