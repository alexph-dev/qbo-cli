# Wave 1 — Uncle Bob Module Extraction (2026-04-11)

Splitting `qbo_cli/cli.py` (1936 LOC monolith) into 12 modules per
`03_notes/2026-04-11-refactor-marathon/plan.md`. Baseline SHA `dcb2a53`.

Hard cutover policy: during extraction (commits 1-12), re-exports live in
`cli.py` with `# noqa: F401` so test patches on `qbo_cli.cli.X` continue to
resolve until commit 13 migrates test imports and patch targets to the
implementation modules.

Gate check after every sub-commit: ruff, ruff format, mypy, pytest,
`qbo --help`, `qbo --version`, `qbo report --list`.
