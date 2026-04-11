# Wave 6 Cannon — Agent A — Packaging / Import / Compat

Scope: `pyproject.toml`, `qbo_cli/__init__.py`, `qbo_cli/cli.py`,
`constants.py`, `errors.py`, `config.py`, `parser.py`, `commands.py`.

## Decisions

- **Python floor**: keep `>=3.9`. No match/case candidates in scope; no
  walrus-in-comprehension; no ParamSpec. Bumping would lose users for zero
  syntactic wins.
- **py.typed (PEP 561)**: added `qbo_cli/py.typed`; hatchling
  `force-include` ensures it lands in the wheel.
- **mypy `check_untyped_defs`**: enabled in pyproject. Baseline already
  clean with the flag (0 new errors) — safe to lock in.
- **ruff rules**: added `B` (bugbear) — 0 violations. Rejected `UP`
  (7 UP037 hits, all in `gl_report.py`, parallel agent scope) and `SIM`
  (5 hits, all in `tests/`, parallel agent scope).
- **`__version__` source of truth**: rewired `qbo_cli/__init__.py` to
  derive from `importlib.metadata.version("qbo-cli")`, with a fallback
  for editable/uninstalled contexts. Drift between `pyproject.toml` and
  `__init__.py` is now impossible.
- **`sys.exit` vs `die()`**: `cli.py` keeps its two `sys.exit(1)` calls
  on "help printed → exit 1" paths. `die()` writes to stderr with an
  `Error:` prefix, which would be wrong there.
- **Dead imports / `__future__` consistency**: all 13 modules already
  have `from __future__ import annotations`. Ruff I001 already clean.
- **Entry point**: `qbo = "qbo_cli.cli:main"` verified.

## Gates

- `ruff check .` green
- `ruff format --check .` green
- `mypy qbo_cli` green (with `--check-untyped-defs` now default)
- `pytest -q` 177/177
- `qbo --help`, `--version`, `report --list` green
- `uv build --wheel` produces wheel containing `qbo_cli/py.typed`
