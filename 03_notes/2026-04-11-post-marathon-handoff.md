# Post-Marathon Handoff — 2026-04-11 20:47 Bangkok

## State at end of session

- **Released**: `v0.9.0 — Refactor Marathon` (https://github.com/alexph-dev/qbo-cli/releases/tag/v0.9.0)
- **HEAD**: `a3ed5bb chore(mypy): include tests in strict typing gate`
- **Origin**: pushed. CI + PyPI workflows green.
- **SonarCloud gate**: OK. Reliability/Security/Maintainability all A. New-code duplication 0.7%.

## Gates at handoff

- `uv run ruff check .` (E/F/W/I/B/UP/SIM) — clean
- `uv run ruff format --check .` — clean (24 files)
- `uv run mypy` — clean (24 source files: 14 qbo_cli + 10 tests/conftest, `check_untyped_defs = true` active)
- `uv run pytest -q` — 177 passed, 29 deselected (live)
- `uv run qbo --version` — `qbo 0.9.0`
- `uv build --wheel` — ships `qbo_cli/py.typed`

## What shipped in v0.9.0

Refactor marathon: `cli.py` 1936 → 109 LOC, split into 13 cohesive modules.
6 expert waves (Uncle Bob → Fowler → Beck → Metz → Henney → Brett Cannon).
52 commits on main. Zero behavior change. Full scoreboard at
`03_notes/2026-04-11-refactor-marathon/README.md`.

## Post-release followup (this session)

6 commits after the v0.9.0 tag:

- `82499f0 docs(architecture)` — `02_docs/architecture.md` rewritten to reflect post-marathon module layout
- `7d0f96a chore` — ruff `UP` + `SIM` rules added; 7 `UP037` quoted-annotation violations auto-fixed in `gl_report.py`
- `5db85c7 fix(tests)` — narrow helper types for mypy
- `07ed80f fix(tests)` — `type-ignore[method-assign]` for pytest mock.method = MagicMock idiom
- `a3ed5bb chore(mypy)` — `[tool.mypy] files = ["qbo_cli", "tests"]` — mypy gate now covers both
- (this handoff note)

## Backlog for next session

From the backlog scanner (`a585087aa37edca56`):

### Quick wins (< 1h each)

- **`auth status` shows active profile** — one-liner in `auth.py cmd_auth_status` around line 287 (wave 4 split it from the orchestrator). Runtime already has the profile name via `Config`.

### Medium work (1–4h each)

- **Direct unit tests for `TokenManager`** — 42% coverage. `refresh_if_needed()`, file locking, chmod 0o600 on write. THEORY.MD flags this as primary regression risk.
- **Direct unit tests for `_run_callback_server` + `cmd_auth_init`** — OAuth callback path (CSRF state check, code exchange, realm_id write). Currently zero direct coverage; only exercised through live tests.
- **`auth init` writes `realm_id` back to config profile** — deferred design item from v0.8.0 profiles feature.

### Large / architectural

- **Python floor bump 3.9 → 3.10** — unlocks `match/case`, `dataclass(slots=True)`, `ParamSpec`. Wave 6 Cannon explicitly deferred: "no syntactic wins today in the current codebase." Needs CI matrix check + README update + classifier tweak.
- **Enable `mypy --strict` incrementally** — 136 errors to clean, but mostly mechanical (`type-arg` = bare `dict`/`list` → `dict[str, Any]`). Order: config → commands → cli_options → cli → client → output → auth → gl_report. 6 modules already strict-clean. 2–3 focused sessions. Use `[[tool.mypy.overrides]]` per-module rather than flipping `--strict` project-wide.
- **Coverage gaps in `gl_report.py`** (52%) — subtotal math, date-range filtering, customer grouping. Wrong subtotals would be silent. Highest-impact test expansion target.

## Useful session-specific context

- **Codex reviews** per wave: all sessions saved to `/tmp/swarm-solo-*/tmp/codex-solo.jsonl`. Session IDs in `03_notes/2026-04-11-refactor-marathon/plan.md` under each wave.
- **Worktree / branches**: none. Direct-to-main per global CLAUDE.md.
- **Origin push history this session**: `9f94185..a3ed5bb`. Two pushes (after wave 6 + after post-marathon followup).
- **PyPI**: v0.9.0 published via trusted publishing workflow `24283350101`.

## Known small drift

- `03_notes/2026-02-17-comprehensive-audit-fixes.md:32` — stale symbol name (`_txn_to_dict`); historical note, not fixed.
- `01_blueprints/` — not touched this session (blueprint = human-verified per CLAUDE.md); if it references pre-marathon structure, flag for Alex review.

## Stop conditions

Session has been running ~5.5h and is context-heavy. Any deeper work on the
backlog items above should start in a fresh session with `pickup` or cold
`cd /Users/alexbukh/dev/qbo-cli`. This handoff note + the marathon scoreboard
(`03_notes/2026-04-11-refactor-marathon/README.md`) are the two documents
future-you should read first.
