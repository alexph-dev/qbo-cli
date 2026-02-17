---
status: pending
priority: p2
issue_id: "004"
tags: [code-review, security]
dependencies: []
---

# LIKE wildcard characters (`%`, `_`) not escaped in QBO queries

## Problem Statement

`_qbo_escape` only doubles single quotes. The `%` and `_` LIKE wildcards pass through unescaped in `_discover_account_tree` and `_resolve_customer` fuzzy search queries. A customer/account name containing `%` would match more results than intended.

## Findings

- **Source:** security-sentinel agent
- **Location:** `qbo_cli/cli.py:50-53` (`_qbo_escape`), lines 692-693, 776-778 (LIKE queries)
- **Impact:** Data over-exposure (more results returned than expected), not data mutation

## Proposed Solutions

### Option A: Extend `_qbo_escape` to escape LIKE wildcards
```python
def _qbo_escape(value: str) -> str:
    return value.replace("'", "''").replace("%", r"\%").replace("_", r"\_")
```
- **Effort:** Small (2 lines)
- **Risk:** Need to verify QBO-QL supports `\%` escape. If not, strip `%`/`_` chars instead.

## Acceptance Criteria

- [ ] `_qbo_escape` handles `%` and `_` characters
- [ ] Fuzzy search with special chars doesn't return overly broad results

## Work Log

- 2026-02-17: Identified during code review
