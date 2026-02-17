# 2026-02-17 — Bugfix: version sync + Python 3.9 compat

## Changes

1. **`__init__.py` version mismatch** — was `0.1.0`, should be `0.6.0` (matches `pyproject.toml` + `cli.py`)
2. **Python 3.9 compat** — `cli.py` used `X | Y` union syntax in type annotations (`dict | None`, `GLTransaction | None`, etc.) which requires 3.10+. Added `from __future__ import annotations` to defer annotation evaluation, fixing runtime `TypeError` on 3.9.

## Files touched

- `qbo_cli/__init__.py` — version bump
- `qbo_cli/cli.py` — added future annotations import

## Verification

- `ruff check` + `ruff format --check` both pass
- No test suite exists yet (noted as follow-up)
