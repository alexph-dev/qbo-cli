# Refactor Marathon — qbo-cli — 2026-04-11

## Baseline

- HEAD: `9f94185` (clean)
- Source: **single file** `qbo_cli/cli.py` (1936 LOC); `__init__.py` (1 LOC, version only)
- Tests: 177 unit tests (excluding `live` marker), all green
- Ruff: 8 issues, 7 auto-fixable (all I001 import ordering in tests/test_pure.py)
- Mypy: 1 error in `tests/test_live_sandbox_crud.py:45` (overload), 3 notes for untyped function bodies in cli.py
- No live QBO credentials available → API smoke limited to `--help`/`--list`/`--version`

## Adaptation of refactor-marathon skill

The skill assumes 10 non-overlapping file scopes for parallel agents. This repo has **one** source file. Direct application is impossible. Adapted pipeline:

- **Gates**: `ruff check .`, `ruff format --check .`, `mypy qbo_cli`, `pytest -q` (177/177), CLI smoke (`qbo --help`, `qbo --version`, `qbo report --list`).
- **Wave 1 is serial** (single agent) — must split the monolith before parallelism is possible.
- **Waves 2–6 are parallel** across extracted modules (4–6 agents per wave, non-overlapping scopes).
- **Expert substitution**: drop Abramov (React-only). Add **Raymond Hettinger** (Pythonic idioms: dataclasses, generators, `functools.cached_property`, pathlib, match/case, itertools pipelines).

## Wave 0 — Green baseline

Sequential, one commit.

1. `ruff check --fix tests/test_pure.py` (fixes 7 I001 import ordering)
2. Fix remaining ruff error (1 non-auto-fixable — inspect and hand-fix)
3. Fix `tests/test_live_sandbox_crud.py:45` mypy overload error
4. Verify: ruff clean, mypy clean, pytest 177/177
5. Commit: `chore: green baseline for refactor marathon`

## Wave 1 — Uncle Bob — Module Extraction (SERIAL, HARD CUTOVER)

Codex review (2026-04-11): hard cutover. No re-export façade. Migrate tests to implementation modules during wave 1. Reasons:

- Tests `@patch('qbo_cli.cli.QBOClient')`, `qbo_cli.cli.CONFIG_PATH`, `qbo_cli.cli.cmd_auth_setup`, etc. If functions resolve globals in their new modules, patches on `qbo_cli.cli.*` silently stop working. Re-export strategy is a landmine.
- Hard-cutover aligns with global CLAUDE.md rule.
- Test migration is a one-time cost paid now; ongoing maintenance is cheaper.

### Target module layout (revised per codex)

```
qbo_cli/
  __init__.py         # version only (unchanged)
  constants.py        # URLs, paths, MINOR_VERSION, OUTPUT_FORMATS, PROFILE_RE, etc.
  errors.py           # die(), err_print()                                    LEAF
  qbo_query.py        # _qbo_escape — query escaping (NOT formatting)         LEAF
  report_registry.py  # REPORT_REGISTRY, _REPORT_ALIAS_MAP,
                      # _resolve_report_name, _format_report_list             LEAF
  output.py           # output, output_text, output_tsv, _output_entity, _truncate,
                      # _normalize_output_data, _has_nested_dict_list,
                      # _unwrap_entity_dict, _first_list_value,
                      # _pad_line, _format_amount, _format_date_range,
                      # _is_month_start, _is_month_end
                      # (NO _parse_date, NO _qbo_escape — those moved)
  cli_options.py      # _resolve_fmt, _parse_date, _make_client,
                      # _emit_result, _read_optional_stdin_json,
                      # _read_stdin_json, _build_report_params
                      # Pure option/param helpers — NO command handlers.
                      # Breaks commands <-> gl_report cycle.
  config.py           # Config class       (depends: constants, errors)
  auth.py             # TokenManager, cmd_auth_*, _run_callback_server
                      # (depends: config, constants, errors — NOT client)
  client.py           # QBOClient          (depends: config, constants, errors, auth)
  gl_report.py        # GLTransaction, GLSection, _parse_txn_from_row,
                      # _parse_gl_rows, _build_section_index, _find_gl_section,
                      # _extract_dates_from_gl, _discover_account_tree,
                      # _list_all_accounts*, _resolve_customer, _compute_subtotal,
                      # _build_report_lines,
                      # _build_txns_report, _collapse_tree,
                      # _build_by_customer_report, _serialize_txn, cmd_gl_report
                      # (depends: client, output, cli_options, qbo_query, errors)
  commands.py         # cmd_query, cmd_search, cmd_get, cmd_create, cmd_update,
                      # cmd_delete, cmd_void, cmd_report, cmd_raw
                      # (depends: client, output, cli_options, report_registry)
  parser.py           # _build_parser, _add_output_arg
                      # (depends: constants, report_registry)
  cli.py              # main(), _resolve_profile, _build_runtime,
                      # _dispatch_command ONLY — thin wiring.
                      # (depends: parser, commands, gl_report, auth, config)
                      # pyproject.toml entry point `qbo = "qbo_cli.cli:main"`
                      # stays valid.
```

### Dependency graph (acyclic)

```
constants ─┐
errors ────┼─► config ──► auth ──► client ──┐
           │                                ├─► gl_report ─┐
qbo_query ─┤                                │              ├─► cli
report_reg ┼─► cli_options ──────────────────┤              │
           │                                ├─► commands ──┘
output ────┴────────────────────────────────┘                ─► parser ─► cli
```

`cli_options` is the key insight: it holds shared option helpers so `gl_report` and `commands` both import from it without importing each other.

### Commit sequence (wave 1) — hard cutover

Each sub-commit green (ruff + mypy + pytest + CLI smoke).

1. `refactor: extract errors and constants modules`
2. `refactor: extract qbo_query module`
3. `refactor: extract report_registry module`
4. `refactor: extract output module`
5. `refactor: extract config module`
6. `refactor: extract auth module`
7. `refactor: extract client module`
8. `refactor: extract cli_options module`
9. `refactor: extract gl_report module`
10. `refactor: extract commands module`
11. `refactor: extract parser module`
12. `refactor: thin cli.py to main() wiring`
13. `refactor(tests): migrate imports and patch targets to implementation modules`

Hard rule: every sub-commit must pass `ruff check . && mypy qbo_cli && pytest -q && uv run qbo --help && uv run qbo report --list` before proceeding. Test migration commit (13) can be batched with commit 12 if diff stays reviewable.

### Complete test surface to migrate

From `rg 'from qbo_cli\.cli import'`:

- `tests/conftest.py`: `Config, QBOClient, TokenManager`
- `tests/test_client.py`: `QBOClient`
- `tests/test_config.py`: `Config, DEFAULT_REDIRECT`
- `tests/test_formatting.py`: `_output_entity, output, output_text, output_tsv`
- `tests/test_parsing.py`: `GLSection, GLTransaction, _parse_gl_rows, _parse_txn_from_row, _build_section_index, _find_gl_section, _extract_dates_from_gl`
- `tests/test_pure.py`: `GLSection, GLTransaction, _build_section_index, _collapse_tree, _find_gl_section, _format_amount, _format_date_range, _is_month_end, _is_month_start, _pad_line, _qbo_escape, _truncate, _serialize_txn`
- `tests/test_commands.py`: `Config, QBOClient, TokenManager, cmd_create, cmd_delete, cmd_get, cmd_gl_report, cmd_query, cmd_raw, cmd_report, cmd_search, cmd_update, cmd_void, cmd_auth_setup` + `@patch` of `qbo_cli.cli.QBOClient`, `qbo_cli.cli.cmd_*`, `qbo_cli.cli.CONFIG_PATH`, `qbo_cli.cli.QBO_DIR`, GL helpers

All patch targets must be updated to point at the new module path where the function resolves its dependencies.

**Exception** (clarified after wave 1): `cli.py` dispatch tests legitimately patch `qbo_cli.cli.cmd_*` — that's where `_dispatch_command` resolves the handler via module globals. So `tests/test_commands.py` dispatch-table tests keep `@patch('qbo_cli.cli.cmd_query')` etc. The "zero qbo_cli.cli hits in tests" goal applies only to symbols that were extracted — not to dispatch glue that legitimately lives in cli.py.

### Risks (revised)

- Patch-target drift: any missed `@patch('qbo_cli.cli.X')` becomes a silent test gap. Mitigation: grep for `qbo_cli.cli` in tests after migration; must be zero hits.
- `_run_callback_server` uses nested `BaseHTTPRequestHandler` subclass capturing `config` — preserve closure.
- `cached_property` usage on `Config.tokens_path` — preserve import.

## Parallelism rules (all waves 2-6)

Codex flagged 4-agent parallelism as unsafe. Revised:

- **Cap at 2 parallel agents per wave**. Strict non-overlap on source files AND test files.
- **Frozen contracts inside a wave**: no signature changes, no import-boundary changes, no public-symbol renames. Those belong to wave 5 (Henney) only.
- **Test file ownership**: each agent owns its test files; cannot touch sibling agent's tests.
- Every wave ends with ruff + mypy + pytest + CLI smoke + `/codex review` before next wave starts.

## Wave 2 — Martin Fowler — Refactoring Catalog (2 agents)

- Agent A scope: `gl_report.py` + `tests/test_parsing.py` + `tests/test_pure.py`
  - Patterns: Replace Loop with Pipeline, Introduce Parameter Object on `_build_report_lines`, Split Phase on `cmd_gl_report`, Combine Functions into Transform on `_parse_gl_rows`.
- Agent B scope: `output.py` + `cli_options.py` + `commands.py` + `tests/test_formatting.py` + `tests/test_commands.py`
  - Patterns: Extract Function on `output_text` (large), Replace Conditional with Polymorphism on format dispatch, Preserve Whole Object on arg passing.

## Wave 3 — Kent Beck — Tidy First (2 agents, `tidy:` commits only)

Structure-only. Any behavior delta reverts the wave.

- Agent A scope: `gl_report.py` + `client.py` + `auth.py`
  - Tidyings: Reading Order, Chunk Statements, Guard Clause, Normal vs Exceptional, Delete Dead Code, Explaining Variable.
- Agent B scope: `output.py` + `cli_options.py` + `commands.py` + `parser.py` + `config.py`
  - Tidyings: Normalize Symmetries, Explaining Comment on intent-sensitive paths, Guard Clause on validation.

## Wave 4 — Sandi Metz — POODR (2 agents)

- Agent A scope: `gl_report.py` + `client.py`
  - Squint Test on `_build_report_lines`, Tell Don't Ask on `GLSection`, Data Clumps to Objects for section/account refs, method length ≤15 on `QBOClient.request`, max 4 params.
- Agent B scope: `auth.py` + `config.py` + `output.py` + `commands.py`
  - Law of Demeter on dict chains, encapsulate token state, colocate state with consumer, reduce feature envy.

## Wave 5 — Kevlin Henney — Naming + Intent (2 agents)

Allowed to rename public symbols — all renames staged as atomic commits with call-site updates.

- Agent A scope: `gl_report.py` + `output.py` + `qbo_query.py` + `report_registry.py`
  - Drop `get`-prefix on pure, `check`-prefix on predicates, parse-don't-validate, noise-word sweep, test names as specifications.
- Agent B scope: `commands.py` + `cli_options.py` + `parser.py` + `auth.py` + `client.py` + `config.py`
  - Intent-revealing, obvious over clever, avoid `None`-then-reassign patterns.

## Wave 6 — Brett Cannon — Packaging / Import / Compat Hygiene (2 agents, replaces Abramov)

Codex review (2026-04-11): Hettinger dropped because `dataclass(slots=True)` and `match/case` are 3.10+, but pyproject.toml targets 3.9. Brett Cannon's domain (packaging, imports, compat) is py3.9-safe AND high ROI for a CLI that's shipped on PyPI.

- Agent A scope: `pyproject.toml` + `qbo_cli/__init__.py` + `cli.py` + import graph
  - Audit: packaging metadata, entry point, lazy imports for slow paths, `from __future__ import annotations` consistency, PEP 561 `py.typed` marker, Python version floor (keep 3.9? bump to 3.10 and unlock match/case?), `importlib.metadata.version` over hardcoded `__version__`.
- Agent B scope: `auth.py` + `client.py` + `gl_report.py` + test suite
  - Audit: stdlib-first imports, `contextlib.suppress` over try/except-pass, `pathlib.Path` over `os.path`, `argparse` type=pathlib.Path, consistent `from __future__ import annotations`, sys.exit/die consistency, test determinism.

Secondary option if Cannon feels too packaging-heavy: Hynek Schlawack (practical testing, structured logging, `attrs` vs `dataclass`, pytest fixture patterns).

## Verification per wave

1. `git log --oneline -1 > baseline-sha`
2. `ruff check .` (clean)
3. `ruff format --check .` (clean)
4. `mypy qbo_cli` (clean or baseline-matched)
5. `pytest -q` (177/177 + new tests if any)
6. CLI smoke: `uv run qbo --help`, `uv run qbo --version`, `uv run qbo report --list`
7. `/codex review` on wave diff; fix findings as atomic `fix(waveN): codex findings — <summary>` commits
8. Push to origin main (after each wave, per CLAUDE.md: direct to main, no branches)
9. Update scoreboard in `03_notes/2026-04-11-refactor-marathon/README.md`

## Scoreboard

| Metric            | W0 | W1 | W2 | W3 | W4 | W5 | W6 |
|-------------------|----|----|----|----|----|----|-----|
| Ruff issues       |    |    |    |    |    |    |    |
| Mypy errors       |    |    |    |    |    |    |    |
| Largest file LOC  |    |    |    |    |    |    |    |
| Total source LOC  |    |    |    |    |    |    |    |
| Test count        |    |    |    |    |    |    |    |

## Codex review — incorporated 2026-04-11

Session: `019d7b9d-f30e-7022-aec2-9e5305470b48`. Findings applied:

1. **Re-exports incomplete** → dropped. Hard cutover, migrate tests.
2. **Tests patch the façade** → test migration is part of wave 1, not optional.
3. **Miscategorized symbols**:
   - `_qbo_escape` → `qbo_query.py` (not output)
   - `_resolve_report_name`, `_format_report_list` → `report_registry.py` (not commands/gl)
   - `_parse_date` → `cli_options.py` (not output)
4. **Circular risk** → introduced `cli_options.py` to break `commands ↔ gl_report` cycle. `auth` no longer depends on `client`.
5. **Wave 6 wrong** → Hettinger replaced with Brett Cannon (py3.9-safe).
6. **Parallelism unsafe** → capped at 2 agents per wave with frozen contracts.
7. Minor: no `functools.partial` in cli.py — incorrect plan reference removed.
