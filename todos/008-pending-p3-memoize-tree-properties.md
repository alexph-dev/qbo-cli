---
status: pending
priority: p3
issue_id: "008"
tags: [code-review, performance]
dependencies: []
---

# `GLSection` tree properties not memoized

## Problem Statement

`all_transactions`, `total_amount`, and `total_count` are recursive `@property` methods that re-walk the entire subtree on every access. Multiple accesses during report rendering cause redundant traversals.

## Findings

- **Source:** performance-oracle agent
- **Location:** `qbo_cli/cli.py:551-565`

## Proposed Solutions

### Option A: Use `functools.cached_property`
Replace `@property` with `@cached_property` on all three. Works on Python 3.8+. `GLSection` doesn't use `__slots__`, so no conflict.
- **Effort:** Small (3 decorator changes + 1 import)
- **Risk:** None — tree is built once, never mutated after construction

## Work Log

- 2026-02-17: Identified during code review
