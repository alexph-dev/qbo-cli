---
title: "feat: Improve report subcommand UX with aliases, validation, and help"
type: feat
status: completed
date: 2026-03-29
---

# feat: Improve report subcommand UX with aliases, validation, and help

## Overview

The `qbo report` subcommand passes the report name verbatim to the QBO API with no validation. Invalid names (e.g. `GL` instead of `GeneralLedger`) produce a cryptic 400 "Permission Denied" error from QBO. This change adds:
1. A canonical report registry with short aliases
2. Client-side validation with actionable error messages
3. `--list` flag to show available reports

## Problem Frame

Running `qbo report GL` returns `API error 400: Permission Denied Error` — misleading because the real issue is an invalid report name, not permissions. Users need discoverable report names and clear errors.

## Requirements Trace

- R1. Invalid report names produce a clear error listing valid options
- R2. Short aliases (GL, PnL, BS, CF, etc.) resolve to canonical API names
- R3. `qbo report --list` shows all available reports with descriptions
- R4. Alias resolution is case-insensitive
- R5. Valid but unlisted report names still pass through (QBO has many reports)

## Scope Boundaries

- No changes to `gl-report` subcommand (separate purpose)
- No changes to report output formatting
- No changes to `QBOClient.report()` method signature

## Context & Research

### Relevant Code and Patterns

- `qbo_cli/cli.py:1607-1610` — `cmd_report` passes `args.report_type` directly to `client.report()`
- `qbo_cli/cli.py:1718-1724` — argparse definition for `report` subcommand
- `qbo_cli/cli.py:65-68` — `die()` for stderr error + exit
- `qbo_cli/cli.py:1538-1553` — `_build_report_params()` pattern to follow

### External References

- QBO Reports API: ProfitAndLoss, BalanceSheet, CashFlow, GeneralLedger, TrialBalance, CustomerIncome, AgedReceivables, AgedPayables, CustomerBalance, VendorBalance, AccountList, TransactionList, ProfitAndLossDetail, BalanceSheetDetail, CustomerSales, VendorExpenses, ItemSales, DepartmentSales, ClassSales

## Key Technical Decisions

- **Registry as module-level dict, not external config**: Small, static, changes only with QBO API updates. A dict of `{alias: (canonical_name, description)}` plus reverse lookup keeps it simple.
- **Pass-through for unknown names with warning**: R5 requires allowing unlisted names since QBO has more reports than we catalog. Print a warning to stderr but don't block.
- **Case-insensitive alias lookup**: Normalize input to match aliases regardless of casing.

## High-Level Technical Design

> *Directional guidance, not implementation specification.*

```
REPORT_ALIASES = {
    "ProfitAndLoss": ("ProfitAndLoss", "Income and expenses summary"),
    "PnL":           ("ProfitAndLoss", "..."),
    "GL":            ("GeneralLedger", "..."),
    ...
}

resolve(name):
    key = case-insensitive lookup in REPORT_ALIASES
    if found -> return canonical name
    else -> warn "unknown report, passing through" -> return name as-is
```

## Implementation Units

- [x] **Unit 1: Report registry and alias resolution**

**Goal:** Add a report name registry with aliases and a resolution function

**Requirements:** R1, R2, R4, R5

**Dependencies:** None

**Files:**
- Modify: `qbo_cli/cli.py`
- Test: `tests/test_commands.py`

**Approach:**
- Add `REPORT_REGISTRY` dict mapping canonical names to descriptions
- Add `REPORT_ALIASES` dict mapping all aliases (including canonical names themselves) to canonical names — case-insensitive keys
- Add `_resolve_report_name(name: str) -> str` that normalizes and looks up, warns on pass-through

**Patterns to follow:**
- Constants section at top of `cli.py` (line 34-50)
- Helper function naming: underscore-prefixed private functions like `_build_report_params`

**Test scenarios:**
- Happy path: canonical name "ProfitAndLoss" resolves to itself
- Happy path: alias "PnL" resolves to "ProfitAndLoss"
- Happy path: alias "GL" resolves to "GeneralLedger"
- Edge case: mixed-case "pnl" resolves correctly
- Edge case: unknown name "CustomReport" passes through with warning on stderr
- Edge case: empty string handled gracefully

**Verification:**
- All aliases resolve to correct canonical names
- Unknown names pass through without error

- [x] **Unit 2: Integrate resolution into cmd_report and add --list**

**Goal:** Wire alias resolution into the report command and add `--list` flag

**Requirements:** R1, R2, R3

**Dependencies:** Unit 1

**Files:**
- Modify: `qbo_cli/cli.py`
- Test: `tests/test_commands.py`

**Approach:**
- In `cmd_report`: call `_resolve_report_name()` before passing to `client.report()`
- Add `--list` flag to the `report` argparse subparser
- When `--list` is set: print registry table (name, aliases, description) and exit
- Update argparse help text to mention `--list` and aliases

**Patterns to follow:**
- `gl-report --list-accounts` pattern at `cli.py:1173` for early-return on list flag
- `_add_output_arg` pattern for argparse additions

**Test scenarios:**
- Happy path: `report PnL` calls API with "ProfitAndLoss"
- Happy path: `report --list` outputs all reports with descriptions, exits without API call
- Happy path: `report GeneralLedger` still works unchanged
- Error path: verify warning message on stderr for unknown report name
- Integration: full argparse round-trip with alias resolves correctly

**Verification:**
- `qbo report GL` succeeds (resolves to GeneralLedger)
- `qbo report --list` shows formatted report table
- `qbo report InvalidName` shows warning but attempts API call

## System-Wide Impact

- **Interaction graph:** Only `cmd_report` affected; `cmd_gl_report` and `QBOClient.report()` unchanged
- **Error propagation:** Invalid names now caught client-side before API call (for known-bad names) or warned (for unknown names)
- **API surface parity:** No other commands need alias resolution
- **Unchanged invariants:** `QBOClient.report()` signature and behavior untouched

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| QBO adds/renames reports | Pass-through (R5) ensures forward compatibility; registry is additive |
| Alias conflicts | Each alias maps to exactly one canonical name; enforce in registry structure |

## Sources & References

- QBO Reports API documentation
- README.md line 210: existing report list
- `cli.py:1167-1213`: gl-report implementation pattern
