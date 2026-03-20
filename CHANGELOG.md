# Changelog

## 0.7.0 (2026-03-20)

- Feature: `qbo search` — generic local text search over query results
- Feature: flexible date input (DD.MM.YYYY, DD/MM/YYYY) with `-e` shorthand
- Feature: `-b`/`--begin` alias for `--start` in `gl-report`
- Security: OAuth `state` parameter validation (CSRF protection)
- Security: lock file permissions restricted to `0o600`
- Performance: O(n) account tree and GL section lookups (was O(n^2))
- Fix: `gl-report` format flags honored across all branches (report + list-accounts)
- Fix: LIKE wildcard `%` no longer stripped in query escaping
- Fix: version defined in single source (`__init__.py`)
- Fix: Python 3.9 compatibility restored (`from __future__ import annotations`)
- Refactor: simplified CLI parser and command dispatch glue
- CI: GitHub Actions pinned to immutable commit SHAs
- Test: comprehensive test suite — 134 tests (was ~10)
- Chore: ast-grep rules for security and code quality linting

## 0.6.0 (2026-02-17)

- Version bump (release automation test)

## 0.5.0 (2026-02-16)

- Fix: author metadata updated in package config

## 0.4.0 (2026-02-16)

- Security: SQL injection prevention, directory permission hardening
- Fix: entity paths auto-lowercase for get/create/update/delete
- Text output for single entities shows key-value pairs

## 0.3.0 (2026-02-16)

- Text output as default for all commands
- Per-subcommand `-o` output flag
- `gl-report --by-customer` / `-g` flag with customer grouping
- `gl-report` output modes: text, json, txns, expanded
- `gl-report --no-sub` flag to roll up sub-accounts
- Customer filter made optional in `gl-report`

## 0.2.0 (2026-02-16)

- `qbo auth setup` interactive config wizard
- `config.json.example` added
- `qbo gl-report` subcommand — hierarchical GL reports by account and customer
- CI/CD: lint workflow + auto-publish to PyPI on release

## 0.1.0 (2026-02-16)

Initial release.

- OAuth 2.0 authentication with local callback server and manual mode
- Query entities with QBO SQL syntax and automatic pagination
- Get, create, update, and delete any QBO entity
- Financial reports (P&L, Balance Sheet, Cash Flow, etc.)
- Raw API access for arbitrary endpoints
- Automatic access token refresh with file locking
- Refresh token expiry warnings
- JSON and TSV output formats
- Sandbox mode support
