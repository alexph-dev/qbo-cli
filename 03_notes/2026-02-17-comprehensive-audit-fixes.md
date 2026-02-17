# 2026-02-17 — Comprehensive Non-Security Audit Fixes

## Summary

16 fixes across 4 files covering documentation inaccuracies, code bugs,
consistency issues, DRY violations, and performance improvements.

## Changes

### Documentation (README.md)
- Removed non-existent `--text` flag from 2 gl-report examples
- Fixed "JSON (default)" → "text (default)" in output format section
- Added `-f json` to jq pipe example (was piping text to jq)
- Fixed redirect URI default: "—" → `http://localhost:8844/callback`
- Added macOS/Linux note (fcntl dependency)

### Metadata (pyproject.toml)
- `Operating System :: OS Independent` → `Operating System :: POSIX`

### CHANGELOG.md
- Backfilled versions 0.2 through 0.6 from git history

### Code (cli.py)
- `_build_section_index`: keys by both name AND id (prevents collision)
- `_find_gl_section`: prefers id-based lookup, 7 callers updated
- `--by-customer` + json/txns: warns instead of silently ignoring
- Dead `elif e_clean` branch removed from `_format_date_range`
- `Config.validate(need_tokens)`: unused param removed, both callers updated
- `create`/`update`/`delete` parsers: added `-o`/`--output` flag
- `auth status`: now uses `_resolve_fmt()` like all other commands
- `_read_stdin_json()`: extracted from duplicate stdin-read pattern
- `_txn_to_dict()`: extracted from duplicate 8-field dict literal
- `import calendar` moved to top-level (was deferred in function body)
- GLSection: `@property` → `@functools.cached_property` (3 properties)
- `output_text`: simplified confusing double-isinstance check

## Verification
- `ruff check` ✓
- `ruff format --check` ✓
- `py_compile` ✓
