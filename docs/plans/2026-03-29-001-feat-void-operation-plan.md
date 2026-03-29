---
title: "feat: Add void operation for QBO entities"
type: feat
status: completed
date: 2026-03-29
---

# feat: Add void operation for QBO entities

## Overview

Add `qbo void <Entity> <ID>` command. QBO void is semantically distinct from delete -- void keeps the transaction on the books as $0 while delete removes it entirely. Invoices, Payments, SalesReceipts, BillPayments, and CreditMemos support void.

## Problem Frame

The CLI supports create/get/update/delete but not void. Void is a common bookkeeping operation needed for correcting transactions without removing audit trail.

## Requirements Trace

- R1. `QBOClient.void()` method: GET entity for SyncToken, POST with `?operation=void`
- R2. `qbo void <Entity> <ID>` CLI command with standard output formatting
- R3. Unit tests for client method and command handler
- R4. Live integration test: create Invoice -> void it -> delete it (cleanup)

## Scope Boundaries

- Only the void operation. No batch, CDC, or attachment support.
- Live test uses Invoice only (most common voidable entity).

## Context & Research

### Relevant Code and Patterns

- `QBOClient.delete()` at `qbo_cli/cli.py:543-546` -- identical pattern (GET then POST with `?operation=` param)
- `cmd_delete()` at `qbo_cli/cli.py:1538-1541` -- 3-line handler pattern
- Parser registration at `qbo_cli/cli.py:1641-1645` -- delete subparser pattern
- Dispatch dict at `qbo_cli/cli.py:1740-1749`
- `TestDelete` at `tests/test_client.py:135-153` -- mock pattern for GET+POST two-step
- Live tests at `tests/test_live.py` -- subprocess-based, `@pytest.mark.live`

## Key Technical Decisions

- **Follow delete's exact pattern**: void is mechanically identical to delete -- GET entity, POST with `?operation=void`. No new abstractions needed.
- **No entity validation**: Keep the CLI generic. QBO API returns clear errors if void isn't supported for an entity.

## Open Questions

### Resolved During Planning

- **Should void validate entity type?** No -- the CLI is entity-agnostic by design. QBO API rejects unsupported entities with a clear Fault message.

### Deferred to Implementation

- **Exact QBO error message for void on non-voidable entities**: Will discover during live testing.

## Implementation Units

- [ ] **Unit 1: Client method + unit tests**

  **Goal:** Add `QBOClient.void()` and its unit test.

  **Requirements:** R1, R3

  **Dependencies:** None

  **Files:**
  - Modify: `qbo_cli/cli.py` (add `void` method after `delete` at ~L546)
  - Test: `tests/test_client.py` (add `TestVoid` class after `TestDelete`)

  **Approach:**
  - Copy delete's pattern: `self.get(entity, entity_id)` -> unwrap -> `self.request("POST", ..., params={"operation": "void"}, json_body=entity_data)`
  - Test mirrors `TestDelete.test_delete_gets_then_posts` -- mock `request.side_effect` with GET+POST responses, assert two calls, assert `params["operation"] == "void"`

  **Patterns to follow:**
  - `QBOClient.delete()` at L543-546
  - `TestDelete` at test_client.py:135-153

  **Test scenarios:**
  - Happy path: void fetches entity via GET then POSTs with `operation=void`, returns result
  - Happy path: entity data is correctly unwrapped from `{"Invoice": {...}}` wrapper

  **Verification:**
  - `uv run pytest tests/test_client.py::TestVoid -v` passes

- [ ] **Unit 2: CLI command + command handler test**

  **Goal:** Add `qbo void` subcommand, handler, and parser registration.

  **Requirements:** R2, R3

  **Dependencies:** Unit 1

  **Files:**
  - Modify: `qbo_cli/cli.py` (add `cmd_void`, parser entry, dispatch entry)
  - Test: `tests/test_commands.py` (add `TestCmdVoid` class)

  **Approach:**
  - `cmd_void` follows `cmd_delete` exactly: make client, call `client.void()`, emit result
  - Parser: `subs.add_parser("void", ...)` with `entity` + `id` args, same as delete
  - Dispatch: add `"void": cmd_void` to dict
  - Import `cmd_void` in test_commands.py, test with mocked client

  **Patterns to follow:**
  - `cmd_delete` at L1538-1541
  - Delete parser at L1641-1645
  - Dispatch dict at L1740-1749
  - Command handler test pattern in test_commands.py

  **Test scenarios:**
  - Happy path: cmd_void calls client.void with correct entity and ID, emits result to stdout

  **Verification:**
  - `uv run pytest tests/test_commands.py::TestCmdVoid -v` passes
  - `qbo void --help` shows usage

- [ ] **Unit 3: Live integration test (create -> void -> delete)**

  **Goal:** End-to-end test creating a test Invoice, voiding it, then deleting it for cleanup.

  **Requirements:** R4

  **Dependencies:** Units 1-2

  **Files:**
  - Modify: `tests/test_live.py` (add `test_live_void_invoice_lifecycle`)

  **Approach:**
  - Create minimal Invoice via `qbo create Invoice` (pipe JSON with minimal required fields: a Line item + CustomerRef)
  - Capture created Invoice ID from JSON output
  - Void it via `qbo void Invoice <ID>`
  - Assert void succeeded (returncode 0)
  - Delete the voided invoice via `qbo delete Invoice <ID>` for cleanup
  - Mark with `@pytest.mark.live`

  **Patterns to follow:**
  - Existing live tests in test_live.py (subprocess.run pattern, timeout=30, json output parsing)

  **Test scenarios:**
  - Happy path: create test Invoice -> void returns success -> voided Invoice can be deleted
  - Error path: void result contains expected entity data (not an error Fault)

  **Verification:**
  - `uv run pytest -m live -k test_live_void -v` passes against real QBO sandbox

## System-Wide Impact

- **Interaction graph:** No callbacks, middleware, or observers affected. Pure additive command.
- **API surface parity:** void completes the CRUD+void operation set alongside get/create/update/delete.
- **Unchanged invariants:** All existing commands, auth flow, GL report engine unaffected.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Live test creates real data in QBO | Use sandbox mode; cleanup via delete after void |
| Minimal Invoice may need specific fields | Check QBO docs for minimum required fields; adjust in live test |
