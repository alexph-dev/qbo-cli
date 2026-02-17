---
status: pending
priority: p1
issue_id: "002"
tags: [code-review, security]
dependencies: []
---

# `tokens.lock` created world-readable (0o644)

## Problem Statement

`TokenManager._locked_refresh` creates `tokens.lock` via `open(lock_path, "w")` with default umask — typically `0o644`. While the lock file is empty, its existence confirms QBO token presence on multi-user systems.

Token file (`tokens.json`) and directory (`~/.qbo/`) have correct restrictive permissions — but the lock file does not.

## Findings

- **Source:** security-sentinel agent
- **Location:** `qbo_cli/cli.py:294-296`
- **Evidence:** Lock file created without `os.chmod()`, unlike `tokens.json` (line 264) and `QBO_DIR` (line 261)

## Proposed Solutions

### Option A: chmod after open (Recommended)
Add `os.chmod(lock_path, 0o600)` immediately after `open(lock_path, "w")`.
- **Effort:** Small (1 line)
- **Risk:** None

## Acceptance Criteria

- [ ] `tokens.lock` has `0o600` permissions after creation
- [ ] Token refresh still works correctly with locked file

## Work Log

- 2026-02-17: Identified during code review
