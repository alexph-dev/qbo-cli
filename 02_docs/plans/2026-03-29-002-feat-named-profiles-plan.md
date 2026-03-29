---
title: "feat: Named profiles for dev/prod credential isolation"
type: feat
status: completed
date: 2026-03-29
deepened: 2026-03-29
---

# feat: Named profiles for dev/prod credential isolation

## Overview

Add named profile support (`prod`/`dev`) so the CLI can manage separate QBO credentials, tokens, and sandbox settings per environment. Intuit provides separate Development and Production key pairs per app -- the CLI should mirror this model.

## Problem Frame

Currently the CLI has a single credential set in `~/.qbo/config.json` and a single token file. The `--sandbox` flag only switches the API base URL, not credentials. This means:
- Using dev keys requires manually swapping config values
- Running `qbo auth init` with sandbox keys overwrites production tokens
- No isolation between environments

Intuit's developer model: one app gets two key pairs (Development + Production), two separate sandbox/production QBO companies (different realm_ids), and two separate OAuth token chains. The CLI should support this natively.

## Requirements Trace

- R1. Config file supports named profile sections (`prod`, `dev`, arbitrary names)
- R2. Each profile has its own client_id, client_secret, realm_id, redirect_uri, sandbox flag
- R3. Each profile has its own token file (`tokens.{profile}.json`)
- R4. `--profile`/`-p` global CLI flag selects profile; `QBO_PROFILE` env var as fallback; default is `prod`
- R5. `--sandbox` becomes alias for `--profile dev`
- R6. Env vars (`QBO_CLIENT_ID`, etc.) still override the selected profile's values
- R7. `qbo auth setup` and `qbo auth init` are profile-aware
- R8. Legacy flat config format is rejected with a clear migration message
- R9. Security invariants preserved: 0o700 dirs, 0o600 files, lock file permissions

## Scope Boundaries

- Only config/token isolation per profile. No per-profile aliases, macros, or command overrides.
- No auto-migration of flat config to profiled format (hard cutover).
- `QBO_SANDBOX` env var is removed -- replaced by `QBO_PROFILE=dev`.
- No limit on profile names, but `prod` and `dev` are the documented convention.

## Context & Research

### Relevant Code and Patterns

- `Config` class at `qbo_cli/cli.py:225-263` -- loads from env vars + config file
- `TokenManager` at `qbo_cli/cli.py:268-381` -- uses module-level `TOKENS_PATH` constant
- `_build_parser()` at `qbo_cli/cli.py:1593` -- `--sandbox` defined as global arg
- `_build_runtime()` at `qbo_cli/cli.py:1734-1739` -- creates Config, applies sandbox override
- `cmd_auth_setup()` at `qbo_cli/cli.py:1386-1447` -- reads/writes `CONFIG_PATH` directly
- Module constants at `qbo_cli/cli.py:36-38` -- `QBO_DIR`, `CONFIG_PATH`, `TOKENS_PATH`

### Institutional Learnings

- `docs/solutions/security-issues/2026-02-17-oauth-csrf-injection-performance-hardening.md`: Lock file must `chmod 0o600` immediately after creation. Per-profile token files must replicate this pattern.

### QBO Developer Model (External Research)

- Each app gets Development + Production credential sets on Intuit's developer portal
- Development keys work only with sandbox companies; Production keys only with live companies
- Sandbox API base URL: `sandbox-quickbooks.api.intuit.com`; Production: `quickbooks.api.intuit.com`
- OAuth endpoint is shared; tokens are per-company per-key-pair

## Key Technical Decisions

- **Single config file, profile-keyed sections**: One `~/.qbo/config.json` with `{"prod": {...}, "dev": {...}}` rather than separate directories per profile. Simpler to manage, one file to back up. Token files stay adjacent as `tokens.{profile}.json`.
- **`prod` as default profile name**: Matches Intuit's model. No `--profile` flag needed for production use -- CLI works the same for existing users after re-running `qbo auth setup`.
- **`--sandbox` = `--profile dev` (profile selection only)**: Preserves the visible, intuitive flag. Semantics change from URL-only switch to full profile selection (dev keys + dev tokens + sandbox URL). `--sandbox` does NOT force `config.sandbox = True` -- sandbox URL routing comes from the profile's `sandbox` field. If the `dev` profile lacks `sandbox: true`, the user gets production URLs.
- **Hard cutover on config format**: Flat config detected by top-level `client_id` key. Clear error message directs user to re-run `qbo auth setup`. No silent migration code.
- **Drop `QBO_SANDBOX` env var**: Replaced by `QBO_PROFILE=dev`. Fewer env vars, cleaner model. `QBO_CLIENT_ID` etc. still override profile values.
- **Module constants become computed**: `TOKENS_PATH` replaced by `Config.tokens_path` property. `CONFIG_PATH` stays (single file). `QBO_DIR` stays (single directory).
- **`realm_id` source of truth is OAuth callback**: `auth init` writes `realm_id` into both the token file (as today) and the config profile section. `auth setup` does not prompt for `realm_id` -- it's populated by `auth init`.
- **`cmd_auth_setup` is the sole config file writer**: `Config._load()` is a reader only. `cmd_auth_setup` owns the profiled JSON schema and handles flat-format detection on write (reads old values as defaults for migration).

## Open Questions

### Resolved During Planning

- **Should `--profile` or `--sandbox` win when both given?** `--profile` wins (explicit > shorthand). Already decided in conversation.
- **Should there be a `default_profile` config key?** No. Default is always `prod`. Users doing extended dev work use `export QBO_PROFILE=dev`.
- **Should legacy flat config auto-migrate?** No. Hard cutover per project rules.

### Deferred to Implementation

- **Exact error message wording for legacy config detection**: Will be refined during implementation.
- **Whether `auth status` should show which profile is active**: Likely yes, but exact formatting deferred.
- **Whether `auth init` should write realm_id back to config profile section**: Design says yes, but exact write-back mechanism deferred.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

### Config File Format

```
~/.qbo/config.json:
{
  "prod": {
    "client_id": "PROD_KEY",
    "client_secret": "...",
    "redirect_uri": "http://localhost:8844/callback",
    "realm_id": "123..."
  },
  "dev": {
    "client_id": "DEV_KEY",
    "client_secret": "...",
    "redirect_uri": "http://localhost:8844/callback",
    "sandbox": true
  }
}
```

### File Layout

```
~/.qbo/
  config.json           # all profiles
  tokens.prod.json      # prod OAuth tokens
  tokens.prod.lock      # lock file (Path.with_suffix('.lock') replaces last suffix)
  tokens.dev.json       # dev OAuth tokens
  tokens.dev.lock
```

### Profile Resolution Flow

```
--profile flag  >  --sandbox (alias for "dev")  >  QBO_PROFILE env  >  "prod"
```

### Data Flow

```
CLI args --> resolve_profile() --> Config(profile=name)
                                      |
                                      +--> _load(): read config.json[profile]
                                      +--> tokens_path: QBO_DIR / f"tokens.{profile}.json"
                                      |
                                  TokenManager(config)
                                      |
                                      +--> load/save/lock use config.tokens_path
```

## Implementation Units

- [ ] **Unit 1: Config profile loading + token path routing**

  **Goal:** Make `Config` accept a `profile` parameter, read the correct section from config.json, and expose a `tokens_path` property. Replace `TOKENS_PATH` usage in `TokenManager` with `config.tokens_path`.

  **Requirements:** R1, R2, R3, R6, R8, R9

  **Dependencies:** None

  **Files:**
  - Modify: `qbo_cli/cli.py` (Config class, TokenManager class, remove `TOKENS_PATH` constant)
  - Test: `tests/test_config.py`
  - Modify: `tests/conftest.py` (add `profile` and `tokens_path` to `fake_config` fixture)

  **Approach:**
  - `Config.__init__(self, profile: str = "prod")` stores `self.profile`
  - `Config._load()` reads raw JSON, detects flat format (top-level `client_id`) and calls `die()` with migration instructions, otherwise reads `raw.get(self.profile, {})`
  - If config file exists with profiles but requested profile is absent, `die()` with `"Profile '{name}' not found. Available: prod, dev"` listing actual keys
  - `Config.tokens_path` property: `QBO_DIR / f"tokens.{self.profile}.json"`
  - Env vars still override profile values (same precedence as today minus `QBO_SANDBOX`)
  - `TokenManager`: replace all `TOKENS_PATH` references with `self.config.tokens_path`
  - Update hardcoded error messages in `TokenManager.load()` (lines 278, 282) to reference `self.config.tokens_path` instead of hardcoded `~/.qbo/tokens.json`
  - Remove `TOKENS_PATH` module constant
  - Remove `QBO_SANDBOX` from `_load()`; `sandbox` is now a profile-level config key only. Keep string-to-bool coercion for the `sandbox` config field (defensive -- users may write `"sandbox": "true"` in JSON)
  - Add startup check: if `QBO_SANDBOX` env var is set, `die()` with message directing user to use `QBO_PROFILE=dev` instead (prevents silent misbehavior after upgrade)
  - **Existing test_config.py tests must be rewritten**: all 9 tests write flat-format JSON and will trigger the new flat-format guard. Rewrite to profiled format. Replace the two `QBO_SANDBOX` env var tests with tests for profile-level `sandbox` key.

  **Patterns to follow:**
  - Existing `Config._load()` structure at `cli.py:236-250`
  - `TokenManager` file operations at `cli.py:275-335`

  **Test scenarios:**
  - Happy path: profiled config loads correct section for `prod` profile
  - Happy path: profiled config loads correct section for `dev` profile
  - Happy path: `dev` profile with `sandbox: true` sets `config.sandbox = True`
  - Happy path: profile without `sandbox` key defaults to `sandbox = False`
  - Happy path: env vars override profile values
  - Happy path: `tokens_path` returns `tokens.prod.json` for prod, `tokens.dev.json` for dev
  - Edge case: missing profile section in existing config triggers `die()` with available profiles listed
  - Edge case: missing config file falls back to empty dict (same as today)
  - Error path: flat config (top-level `client_id`) triggers `die()` with migration message
  - Error path: invalid JSON still handled gracefully
  - Error path: corrupt token file error message includes profile-specific path

  **Verification:**
  - `uv run pytest tests/test_config.py -v` passes
  - `uv run mypy qbo_cli` passes

- [ ] **Unit 2: CLI flag wiring (`--profile`, `--sandbox` alias, `QBO_PROFILE`)**

  **Goal:** Add `--profile`/`-p` global arg, make `--sandbox` an alias for `--profile dev`, wire profile resolution through `_build_runtime`.

  **Requirements:** R4, R5

  **Dependencies:** Unit 1

  **Files:**
  - Modify: `qbo_cli/cli.py` (`_build_parser`, `_build_runtime`)
  - Test: `tests/test_commands.py`
  - Modify: `tests/conftest.py` (update `make_args` defaults)

  **Approach:**
  - `_build_parser()`: replace `--sandbox` with `--profile`/`-p` and `--sandbox` (both on root parser)
  - `--profile` takes a string argument (default: None)
  - `--sandbox` stays as `action="store_true"`
  - `_build_runtime(args)`: resolve profile from `args.profile > ("dev" if args.sandbox) > QBO_PROFILE env > "prod"`. Pass to `Config(profile=resolved)`. Remove the `if args.sandbox: config.sandbox = True` line -- sandbox is now a profile-level setting.
  - `make_args()` in conftest: add `profile=None`, keep `sandbox=False`
  - Update existing test_commands.py tests that mock `Config()` -- the mock must accept a `profile` keyword argument or existing tests will break

  **Patterns to follow:**
  - Existing `_build_runtime` at `cli.py:1734-1739`
  - Parser global args at `cli.py:1599-1601`

  **Test scenarios:**
  - Happy path: `--profile dev` resolves profile to "dev"
  - Happy path: `--sandbox` resolves profile to "dev"
  - Happy path: no flags, no env var resolves to "prod"
  - Happy path: `QBO_PROFILE=dev` env var resolves to "dev" when no flag given
  - Happy path: `--profile custom` works with arbitrary profile names
  - Edge case: `--profile prod --sandbox` -- `--profile` wins over `--sandbox`

  **Verification:**
  - `uv run pytest tests/test_commands.py -v` passes
  - `qbo --help` shows `--profile` and `--sandbox` flags

- [ ] **Unit 3: Profile-aware `auth setup` and `auth init`**

  **Goal:** Make `auth setup` read/write the profiled config format. Make `auth init` work with the resolved profile (tokens save to correct file). Update `auth status` to show active profile.

  **Requirements:** R7

  **Dependencies:** Units 1-2

  **Files:**
  - Modify: `qbo_cli/cli.py` (`cmd_auth_setup`, `cmd_auth_status`)
  - Test: `tests/test_commands.py`

  **Approach:**
  - `cmd_auth_setup` is the **sole writer** of `config.json` and owns the profiled schema. It reads existing config.json, detects flat format (reads old values as defaults for the target profile — serves as migration path), reads/updates the profile section, writes back full profiled dict using atomic write (temp file + chmod 0o600 + rename, same pattern as `TokenManager.save`). Shows which profile is being configured in prompts. Does NOT prompt for `realm_id` (populated by `auth init`).
  - `cmd_auth_init`: needs one change — after `exchange_code()`, write the OAuth callback's `realm_id` back into the config profile section (in addition to the token file). This makes `realm_id` available for subsequent commands without requiring manual config.
  - `cmd_auth_status`: add `profile` field to the status output. Update user-facing strings at `validate()` to mention `qbo auth setup --profile <name>`.

  **Patterns to follow:**
  - Existing `cmd_auth_setup` at `cli.py:1386-1447`
  - Existing `cmd_auth_status` at `cli.py:1361-1376`

  **Test scenarios:**
  - Happy path: `auth setup` with `--profile dev` writes to dev section of config.json
  - Happy path: `auth setup` without flags writes to prod section
  - Happy path: `auth setup` for one profile preserves other profiles in config
  - Happy path: `auth status` shows active profile name in output
  - Edge case: `auth setup` on empty/missing config.json creates profiled format from scratch
  - Edge case: `auth setup` on flat config creates fresh profiled format (doesn't crash)

  **Verification:**
  - `uv run pytest tests/test_commands.py -v` passes
  - `uv run ruff check qbo_cli/cli.py` passes

- [ ] **Unit 4: Update docs, example config, and fixtures**

  **Goal:** Update config.json.example, architecture.md, conftest fixtures, and README usage examples.

  **Requirements:** R1-R9 (documentation)

  **Dependencies:** Units 1-3

  **Files:**
  - Modify: `config.json.example`
  - Modify: `02_docs/architecture.md`
  - Modify: `README.md` (usage examples)

  **Approach:**
  - `config.json.example`: show profiled format with `prod` and `dev` sections
  - `architecture.md`: update Config/TokenManager descriptions to mention profile routing, update file layout section
  - `README.md`: update usage examples with `--profile`/`--sandbox`, explain dev/prod setup

  **Patterns to follow:**
  - Existing architecture.md structure
  - Existing README.md style

  **Test scenarios:** N/A (documentation only)

  **Verification:**
  - Documentation accurately reflects new behavior
  - `config.json.example` is valid JSON

- [ ] **Unit 5: Live test with dev keys**

  **Goal:** Configure dev profile with the provided development keys, run OAuth flow, verify sandbox queries work.

  **Requirements:** R1-R5 (end-to-end verification)

  **Dependencies:** Units 1-4

  **Files:**
  - Modify: `tests/test_live.py` (add profile-aware live tests)

  **Approach:**
  - Write dev profile credentials to `~/.qbo/config.json` (dev section with provided keys + `sandbox: true`)
  - Run `qbo -p dev auth init` to complete OAuth flow against sandbox
  - Add live test: `test_live_dev_profile_query` -- runs `qbo --sandbox query "SELECT * FROM CompanyInfo"` and verifies sandbox response
  - Mark with `@pytest.mark.live`

  **Patterns to follow:**
  - Existing live tests in `test_live.py` (subprocess-based, `timeout=30`)

  **Test scenarios:**
  - Happy path: `qbo --sandbox query "SELECT * FROM CompanyInfo"` returns valid sandbox company data
  - Happy path: `qbo --sandbox auth status` shows valid tokens for dev profile

  **Verification:**
  - `uv run pytest -m live -k test_live_dev -v` passes against real QBO sandbox

## System-Wide Impact

- **Interaction graph:** Auth commands, all entity commands, and report commands are affected through the Config/TokenManager layer. No command handler changes needed (they receive config/token_mgr from `_build_runtime`).
- **API surface parity:** `--sandbox` retains its position as a visible CLI flag. `--profile` adds new capability.
- **Unchanged invariants:** All entity and report command handlers (query/get/create/update/delete/void, report, gl-report, raw) need no direct changes. Auth command handlers require profile-aware updates as detailed in Unit 3. `Config.validate()` error messages should reference `--profile`.
- **State lifecycle:** Token files are per-profile. No risk of cross-profile token overwrites.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Breaking existing `~/.qbo/config.json` for current users | Clear error message with exact migration steps. `qbo auth setup` recreates in new format. |
| Live test requires interactive OAuth flow | Use `--manual` mode or run interactively before test suite |
| Lock file contention across profiles | Each profile has its own lock file -- no contention |
| `QBO_SANDBOX` removal breaks scripts using it | Hard cutover. Document in changelog. Replacement: `QBO_PROFILE=dev` |
| Concurrent `auth setup` or `auth init` on different profiles | Both read-modify-write `config.json` without locking. Unlikely (interactive commands). Known limitation, no fix needed. |
| All existing test_config.py tests write flat format | Must be rewritten to profiled format in Unit 1. 9 test cases affected. |

## Sources & References

- Intuit Developer Docs: sandbox companies, Development vs Production keys
- `docs/solutions/security-issues/2026-02-17-oauth-csrf-injection-performance-hardening.md`
- Existing void operation plan: `docs/plans/2026-03-29-001-feat-void-operation-plan.md` (pattern reference)
