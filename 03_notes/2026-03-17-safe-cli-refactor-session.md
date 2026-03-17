# Safe CLI Refactor Session

Date: 2026-03-17

## Scope

- Refactor internal structure of `qbo_cli/cli.py`
- Do not change QuickBooks Online data
- Keep behavior stable and tests green

## Changes

- extracted parser helpers:
  - `_add_output_arg()`
  - `_build_parser()`
  - `_build_runtime()`
  - `_dispatch_command()`
- extracted shared command helpers:
  - `_make_client()`
  - `_emit_result()`
  - `_read_optional_stdin_json()`
  - `_build_report_params()`
- centralized shared output normalization:
  - `_unwrap_entity_dict()`
  - `_first_list_value()`
  - `_normalize_output_data()`
  - `_has_nested_dict_list()`
- applied small typing cleanups that let `mypy qbo_cli` pass
- added architecture map in `02_docs/architecture.md`
- updated `THEORY.MD` to reflect the new operating theory

## Verification

- `.venv/bin/ruff check qbo_cli/cli.py`
- `.venv/bin/mypy qbo_cli`
- `.venv/bin/pytest`

## Results

- `ruff`: pass
- `mypy`: pass
- `pytest`: `124 passed, 10 deselected`

## Notes

- Existing unrelated worktree changes were preserved:
  - `AGENTS.md`
  - `03_notes/api-demo.md`
  - `uv.lock`
