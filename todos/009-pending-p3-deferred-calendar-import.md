---
status: pending
priority: p3
issue_id: "009"
tags: [code-review, quality]
dependencies: []
---

# `import calendar` deferred inside function body

## Problem Statement

`_is_month_end` (line 809) has `import calendar` inside the function body while all other stdlib imports are at the top of the file. Inconsistent with codebase conventions.

## Findings

- **Source:** python-reviewer, architecture-strategist, pattern-recognition agents (all flagged)
- **Location:** `qbo_cli/cli.py:809`

## Proposed Solutions

### Option A: Move to top-level imports
Move `import calendar` to the stdlib import block at the top of the file.
- **Effort:** Small (move 1 line)
- **Risk:** None

## Work Log

- 2026-02-17: Identified during code review
