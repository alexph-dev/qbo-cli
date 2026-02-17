---
status: pending
priority: p2
issue_id: "003"
tags: [code-review, architecture]
dependencies: []
---

# Version defined in 3 places — DRY violation

## Problem Statement

`__version__` is independently defined in `pyproject.toml`, `qbo_cli/__init__.py`, and `qbo_cli/cli.py`. This already caused the `0.1.0` drift bug that was just fixed. Will happen again on next bump.

## Findings

- **Source:** python-reviewer, architecture-strategist, simplicity-reviewer (all 3 flagged)
- **Locations:** `pyproject.toml:7`, `qbo_cli/__init__.py:1`, `qbo_cli/cli.py:29`

## Proposed Solutions

### Option A: Import chain (Recommended)
- Keep `pyproject.toml` (build system requires it)
- Keep `__init__.py` (canonical Python source)
- In `cli.py`: replace `__version__ = "0.6.0"` with `from qbo_cli import __version__`
- **Effort:** Small (1 line change)
- **Risk:** None — circular import not possible since `__init__.py` has no imports from `cli`

### Option B: `importlib.metadata` (single source)
- Remove `__init__.py` version, use `importlib.metadata.version("qbo-cli")`
- **Effort:** Small
- **Risk:** Requires try/except for `PackageNotFoundError` (running from source without install)

## Acceptance Criteria

- [ ] Version defined in at most 2 places (pyproject.toml + one import)
- [ ] `qbo --version` shows correct version
- [ ] `from qbo_cli import __version__` returns correct version

## Work Log

- 2026-02-17: Identified during code review
