# 2026-02-17 — Code Review: P1+P2 Fixes

## Changes (6 findings resolved)

### P1 — Critical
1. **OAuth state CSRF** — `state` param now validated in both callback server and manual mode. Mismatched state returns 400.
2. **Lockfile permissions** — `tokens.lock` now gets `0o600` via `os.chmod` immediately after creation.

### P2 — Important
3. **Version triplication** — removed duplicate `__version__` from `cli.py`; now imports from `__init__.py`. Single source of truth (pyproject.toml + __init__.py).
4. **LIKE wildcard escape** — `_qbo_escape` strips `%` to prevent unintended pattern matching.
5. **O(n^2) account tree** — `_discover_account_tree`, `_list_all_accounts`, and GL section lookups now use pre-built dicts (`children_by_parent`, `_build_section_index`) for O(n) instead of O(n^2).
6. **CI SHA pinning** — all GitHub Actions in lint.yml and publish.yml pinned to immutable commit SHAs.

## Files touched
- `qbo_cli/cli.py` — all P1+P2 code fixes
- `.github/workflows/lint.yml` — SHA pinning
- `.github/workflows/publish.yml` — SHA pinning
- `todos/` — 9 finding files (6 complete, 3 pending P3)

## Verification
- `ruff check` + `ruff format --check` both pass
- Version import verified: `from qbo_cli import __version__` → `0.6.0`
