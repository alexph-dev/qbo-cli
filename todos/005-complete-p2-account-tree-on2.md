---
status: pending
priority: p2
issue_id: "005"
tags: [code-review, performance]
dependencies: []
---

# O(n^2) algorithms in account tree operations

## Problem Statement

Three functions scan the entire `all_accts` list per recursive call: `build_children` (line 703), `count_descendants` (line 729), and `_find_gl_section` (line 644). At 500+ accounts, these compound to noticeable latency.

## Findings

- **Source:** performance-oracle agent
- **Locations:**
  - `qbo_cli/cli.py:703-716` — `build_children` in `_discover_account_tree`
  - `qbo_cli/cli.py:729-734` — `count_descendants` in `_list_all_accounts`
  - `qbo_cli/cli.py:644-652` — `_find_gl_section` repeated linear scans

## Proposed Solutions

### Option A: Pre-build lookup dicts (Recommended)
- Build `children_map = defaultdict(list)` once from `all_accts`
- Build `section_index: dict[str, GLSection]` once from `_parse_gl_rows` result
- Replace all linear scans with O(1) dict lookups
- `defaultdict` is already imported
- **Effort:** Medium (~30 lines total across 3 functions)
- **Risk:** Low — internal change, no API/CLI behavior change

## Acceptance Criteria

- [ ] `_list_all_accounts` uses O(n) preprocessing
- [ ] `_discover_account_tree` uses O(n) preprocessing
- [ ] GL report rendering uses indexed section lookups
- [ ] Output is identical before and after

## Work Log

- 2026-02-17: Identified during code review
