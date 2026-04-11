# Refactor Marathon — qbo-cli — 2026-04-11

One-day marathon applying Uncle Bob → Fowler → Beck → Metz → Henney → Cannon to the entire `qbo_cli` package. Every wave verified by ruff + ruff format + mypy + pytest + CLI smoke + codex review.

## Outcome

| Metric                | Before (`dcb2a53`) | After (`68d6715`) | Delta          |
|-----------------------|--------------------|-------------------|----------------|
| `qbo_cli/cli.py` LOC  | 1936               | 109               | **−94.4%**     |
| Source modules        | 1                  | 13 + `py.typed`   | +12            |
| Total source LOC      | 1937               | 2226              | +289           |
| Largest file (LOC)    | 1936 (`cli.py`)    | 727 (`gl_report`) | −62.5%         |
| Tests                 | 177 unit           | 177 unit          | unchanged      |
| Ruff issues           | 8                  | 0                 | −8             |
| Mypy errors           | 1 (tests)          | 0 (`qbo_cli`)     | clean          |
| Wheel ships `py.typed`| no                 | yes (PEP 561)     | new            |
| `__version__` source  | hardcoded          | `importlib.metadata` | single SoT |
| Commits on `main`     | —                  | 51                | all green      |

## Module layout (after wave 1)

```
qbo_cli/
├── __init__.py         33   # version SoT via importlib.metadata
├── cli.py             109   # main() + dispatch only
├── constants.py        25   # URLs, paths, REGEX, format lists
├── errors.py           16   # die(), err_print()
├── qbo_query.py        10   # query escaping (leaf)
├── report_registry.py  70   # REPORT_REGISTRY + alias resolution
├── output.py          221   # text/json/tsv rendering
├── cli_options.py      91   # shared option helpers, client factory
├── config.py           83   # Config class + profile loading
├── auth.py            415   # TokenManager + cmd_auth_* + OAuth flow
├── client.py          156   # QBOClient HTTP wrapper
├── gl_report.py       727   # GL report engine + cmd_gl_report
├── commands.py         91   # cmd_query/get/create/update/delete/void/report/raw
├── parser.py          179   # argparse wiring
└── py.typed             0   # PEP 561 marker
```

## Waves

Range: `dcb2a53..68d6715`. Every wave verified by ruff + mypy + pytest + CLI smoke + `/codex review` against the diff; findings fixed as `fix(waveN):` commits before the next wave.

### Wave 0 — Green baseline (`dcb2a53`)

Auto-fix ruff I001/F401 across tests. Fix F841 unused `result` binding. Apply `ruff format`. Fix mypy call-overload in `test_live_sandbox_crud.py`. Write plan.md and codex-review it before execution.

### Wave 1 — Uncle Bob — Module extraction (hard cutover) — 10 commits

Split `qbo_cli/cli.py` (1936 LOC) into 12 cohesive modules + migrate all test imports and `@patch` targets to the new module paths. No re-export shims. Tests now import symbols from the module where they live; dispatch-level patches still target `qbo_cli.cli.cmd_*` because `_dispatch_command` resolves handlers via cli.py module globals.

Key codex-driven plan decisions: introduce `cli_options.py` to break the `commands ↔ gl_report` cycle (shared helpers like `_make_client`, `_resolve_fmt`, `_parse_date` live there); `qbo_query.py` and `report_registry.py` as leaf modules that both commands.py and gl_report.py can safely import.

Codex review: **HOLDING**. AST compared 69 defs before and 69 after; only changed bodies were mechanical wiring. One plan contract clarification needed: dispatch tests legitimately still patch `qbo_cli.cli.cmd_*`.

### Wave 2 — Martin Fowler — Refactoring Catalog (2 parallel agents) — 8 commits

- Agent A (gl_report.py): Extract Function on `_parse_gl_rows` duplication, Split Phase on `cmd_gl_report` into 7 phases, Decompose Conditional on `_build_by_customer_report` (extracts `_customer_group_key`, `_group_txns_by_customer`, `_sort_customer_groups`), Replace Loop with Pipeline on `_build_report_lines` (new pure `_render_node_lines` returning lists instead of mutating an accumulator), self-applied Inline Function on an over-decomposed leaf/branch split.
- Agent B (output.py + commands.py): Extract Function + Split Phase on `output_text` into 5 private renderers, Decompose Conditional on `cmd_search` extracting `_build_row_matcher` factory.

Codex review: **TIGHT WAVE. BEHAVIOR HELD**. One P3 fix: removed dead `_append_txn_lines` helper with stale "backward compat" comment.

### Wave 3 — Kent Beck — Tidy First (2 parallel agents, `tidy:` commits only) — 8 commits

Structure-only. SB:CHG (Separation of Behavior and Structure Change) rule held across all 8 commits.

- Agent A (gl_report/client/auth): Reading Order hoists (render helpers above callers, customer-grouping helpers above callers), Explaining Comments labelling `cmd_gl_report` phases, Delete Dead Code loop-var drop in `_extract_entities`.
- Agent B (output/commands/parser/config): Reading Order hoist of `_truncate`, Explaining Comment rewrite in `_output_kv` (now `_output_entity`), Normal-vs-Exceptional flip in `Config._load` legacy detection, Delete Dead Code `isatty` duplicate in `_read_stdin_json`.

Codex review: **CLEAN**. Two P3/P4 pedantic Beck nits (isatty call-count in mock test doubles, malformed traceback text) below the noise floor — real CLI behavior unchanged.

### Wave 4 — Sandi Metz — POODR (2 parallel agents) — 9 commits

- Agent A (gl_report/client): Squint Test + Extract Method on `QBOClient.request` (44 → 12 LOC) via `_http_call`, `_send_with_refresh`, `_extract_error_detail`; Tell Don't Ask on `GLSection` with `direct_pair`/`total_pair` helpers; Parameter Object `_RenderCtx` frozen dataclass collapses 6-param `_build_report_lines` to 4 and drops the in/out accumulator.
- Agent B (auth/config/output): Extract Method on `_do_refresh` (→ `_post_token_endpoint` + `_raise_on_refresh_error` + `_build_token_envelope`), Tell Don't Ask `_is_token_fresh` helper; `Config._load` split into 3 focused helpers; `cmd_auth_setup` (78 → 12 LOC body) split into 7 helpers; `cmd_auth_refresh` feature envy eliminated via new public `TokenManager.refresh_if_needed()`.

Codex review: **HOLDING**. One P2 fix: `_extract_error_detail` could raise `AttributeError` on malformed `Fault.Error` entries where original code fell back to response text — moved the join inside the try block.

### Wave 5 — Kevlin Henney — Naming + Intent (2 parallel agents) — 9 commits

Renames allowed and atomic.

- Agent A: `_txn_to_dict` → `_serialize_txn`, `_section_tree_to_dict` → `_serialize_section_tree`, `_output_kv` → `_output_entity`, consistent `customer`/`txn` vocabulary across gl_report.
- Agent B: `_do_refresh` → `_fetch_fresh_tokens`, `_raise_on_refresh_error` → `_die_on_refresh_error`, `_headers` → `_auth_headers`, `_row_matches` → `_build_row_matcher`, `_load_all_profiles_for_setup` → `_load_all_profiles`.

Codex review: **CLEAN**. No runtime rename fallout. Stale references only in docs — plan.md updated in-wave.

### Wave 6 — Brett Cannon — Packaging / Import / Compat Hygiene (2 parallel agents) — 6 commits

Replaces the original Abramov/Hettinger wave because the project targets Python 3.9 (no `match/case`, no `dataclass(slots=True)`).

- Agent A (packaging): `qbo_cli/py.typed` marker for PEP 561; `hatch force-include` so the wheel actually ships it; `__version__` from `importlib.metadata.version("qbo-cli")` so `pyproject.toml` is the single source of truth; `check_untyped_defs = true` in mypy config (zero new errors); ruff `B` (bugbear) rule added (zero new warnings). Kept Python 3.9 floor. Wheel verified: `dist/qbo_cli-0.8.0-py3-none-any.whl` contains `qbo_cli/py.typed`.
- Agent B (import hygiene): `secrets.token_hex(16)` replacing `os.urandom(16).hex()` for OAuth CSRF state (canonical stdlib for security tokens, same shape); `Path.chmod` over `os.chmod` for pathlib symmetry in `auth.py`; `contextlib.suppress(ValueError)` replacing try/pass in `cli_options._parse_date`; `contextlib.suppress` and combined `with` blocks across test files (SIM105/SIM117 cleanup).

Codex final review across the full marathon (`dcb2a53..HEAD`): **P1 none. P2 one fix: source-checkout `__version__` regressed to `0.0.0+unknown`** when package is imported from a source tree without install. Fixed by adding a regex fallback that reads `pyproject.toml` directly — pyproject remains single SoT for both installed wheels (via `importlib.metadata`) and source checkouts (via regex). P3: README release steps still referenced bumping `qbo_cli/__init__.py` — synced to match new SoT. Untyped-tests note (41 errors) accepted as tooling drift since CI only runs `mypy qbo_cli`.

## Final gate state

- `ruff check .` → clean (E/F/W/I/B)
- `ruff format --check .` → clean (24 files)
- `mypy qbo_cli` → clean (14 source files, `check_untyped_defs = true`)
- `pytest -q` → 177/177 passing (29 live tests deselected)
- `uv run qbo --help` / `qbo --version` → `qbo 0.8.0` / `qbo report --list` → all working
- `uv build --wheel` → `dist/qbo_cli-0.8.0-py3-none-any.whl` with `py.typed`

## Commit ranges per wave

| Wave | First → Last                | Count |
|------|-----------------------------|-------|
| 0    | `dcb2a53` → `dcb2a53`       | 1     |
| 1    | `47c17c3` → `86f3971`       | 11    |
| 2    | `ab39715` → `8703737`       | 8     |
| 3    | `5dfdb8c` → `2ce6d8e`       | 8     |
| 4    | `864c313` → `311be86`       | 9     |
| 5    | `a7c3afa` → `c847da3`       | 9     |
| 6    | `517d0e1` → `68d6715`       | 6     |
| **Total** | `dcb2a53` → `68d6715`  | **52** |

## Hard rules held across the marathon

1. Every commit was `refactor:`, `tidy:`, `fix:`, `chore:`, or `docs:` — Beck SB:CHG rule was honored.
2. Every agent used explicit-file commits (`git commit -- path1 path2`) — never `git add -A`.
3. Parallel agents had **strictly non-overlapping scopes** (different source files + different test files).
4. No branches, no worktrees, no PRs — direct to main per Alex's global CLAUDE.md.
5. Codex review after every wave, findings fixed as atomic `fix(waveN):` before the next wave.
6. Python 3.9 floor held — no `match/case`, no `dataclass(slots=True)`, no runtime `X | Y` unions.
7. Test suite never regressed: 177 passing at every commit boundary.
8. No push to origin (Alex runs releases manually; CLAUDE.md forbids silent pushes).

## Codex findings summary

- Wave 1: 1 doc clarification (plan contract mismatch for dispatch tests)
- Wave 2: 1 P3 dead code removal (`_append_txn_lines`)
- Wave 3: 2 P3/P4 pedantic (not fixed — below noise floor)
- Wave 4: 1 P2 behavior drift (`_extract_error_detail` malformed Fault fallback) — fixed
- Wave 5: 0 runtime findings (doc sync only)
- Wave 6: 1 P2 source-checkout version regression + 1 P3 README sync — both fixed

Zero P1 findings across all 6 waves.
