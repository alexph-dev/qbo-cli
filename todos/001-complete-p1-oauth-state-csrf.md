---
status: pending
priority: p1
issue_id: "001"
tags: [code-review, security]
dependencies: []
---

# OAuth `state` parameter not validated — CSRF risk

## Problem Statement

The OAuth callback handler in `_run_callback_server` accepts any `code` parameter without verifying the `state` value. A CSRF attack could bind the CLI to an attacker-controlled QBO realm by tricking the local callback into accepting an attacker-initiated auth code.

The `state` is correctly generated (`os.urandom(16).hex()` at line 1192) but never checked in the callback handler (line 1222).

## Findings

- **Source:** security-sentinel agent
- **Location:** `qbo_cli/cli.py:1192` (generation), `qbo_cli/cli.py:1222-1225` (missing validation)
- **Risk:** An attacker on the same network could redirect to `localhost:8844/callback?code=ATTACKER_CODE&realmId=ATTACKER_REALM&state=anything` and the handler would accept it

## Proposed Solutions

### Option A: Thread state into handler closure (Recommended)
- Pass `expected_state` into the handler via closure
- Check `qs.get("state", [None])[0] != expected_state` → return 400
- **Effort:** Small (~10 lines)
- **Risk:** None

## Acceptance Criteria

- [ ] Generated `state` value is compared against callback `state` parameter
- [ ] Mismatched state returns HTTP 400 with error message
- [ ] Manual test: auth flow completes normally with valid state

## Work Log

- 2026-02-17: Identified during code review
