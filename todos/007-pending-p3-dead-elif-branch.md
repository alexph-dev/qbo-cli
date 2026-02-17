---
status: pending
priority: p3
issue_id: "007"
tags: [code-review, quality]
dependencies: []
---

# Dead `elif e_clean` branch in `_format_date_range`

## Problem Statement

Lines 826-827 (`elif e_clean:`) produce the same string as the `else:` branch on line 828. The `elif` is unreachable dead logic.

## Findings

- **Source:** simplicity-reviewer agent
- **Location:** `qbo_cli/cli.py:824-828`

## Proposed Solutions

### Option A: Remove the dead branch
Delete `elif e_clean:` and its body, keeping just `else:`.
- **Effort:** Small (delete 2 lines)
- **Risk:** None

## Work Log

- 2026-02-17: Identified during code review
