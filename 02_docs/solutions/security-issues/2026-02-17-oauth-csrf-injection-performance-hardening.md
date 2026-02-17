---
title: "qbo-cli: Security + performance hardening (8 fixes)"
date: 2026-02-17
category: security-issues
tags:
  - oauth
  - csrf
  - file-permissions
  - sql-injection
  - performance
  - ci-hardening
  - python-compat
  - version-sync
severity: high
status: resolved
components:
  - qbo_cli/cli.py
  - qbo_cli/__init__.py
  - .github/workflows/lint.yml
  - .github/workflows/publish.yml
root_cause: Multiple pre-existing issues surfaced during 6-agent code review
resolution: 2 P1 security fixes, 4 P2 fixes (security + performance + quality)
commits:
  - 23452e3  # fix: sync __init__ version + restore Python 3.9 compat
  - 9cf3825  # fix: resolve P1+P2 findings from code review
---

# Security + Performance Hardening Session

## Problem

Code review of qbo-cli (single-file Python CLI for QuickBooks Online API) surfaced 9 findings across security, performance, and code quality. Two were critical (P1), four important (P2), three nice-to-have (P3).

## Fixes Applied

### P1 — Critical Security

#### 1. OAuth `state` parameter not validated (CSRF)

The OAuth callback handler accepted any `code` without checking the `state` parameter. An attacker could redirect to `localhost:8844/callback?code=ATTACKER_CODE&realmId=ATTACKER_REALM` and bind the CLI to their realm.

**Fix:** Thread `expected_state` into both the callback server handler and manual mode, reject mismatches with HTTP 400.

```python
# cmd_auth_init — extract state for validation
oauth_state = os.urandom(16).hex()
# ... pass to _run_callback_server(auth_url, config, args.port, oauth_state)

# _run_callback_server — validate in handler
def do_GET(self):
    qs = parse_qs(urlparse(self.path).query)
    if qs.get("state", [None])[0] != expected_state:
        self.send_response(400)
        self.end_headers()
        self.wfile.write(b"State mismatch - possible CSRF. Try again.")
        return
```

**Location:** `qbo_cli/cli.py` lines 1197-1219, 1230-1244

#### 2. `tokens.lock` created world-readable

Lock file created via `open(lock_path, "w")` inherited default umask (typically 0o644). Token file and directory had correct permissions, but lock file did not.

**Fix:** Add `os.chmod(lock_path, 0o600)` immediately after `open()`.

```python
with open(lock_path, "w") as lock_file:
    os.chmod(lock_path, 0o600)  # restrict before locking
    fcntl.flock(lock_file, fcntl.LOCK_EX)
```

**Location:** `qbo_cli/cli.py` line 297

### P2 — Important

#### 3. Version defined in 3 places (DRY violation)

`__version__` independently defined in `pyproject.toml`, `__init__.py`, and `cli.py`. Already caused `0.1.0` vs `0.6.0` drift.

**Fix:** Removed duplicate from `cli.py`, now imports from `__init__.py`:

```python
# cli.py — was: __version__ = "0.6.0"
from qbo_cli import __version__
```

**Location:** `qbo_cli/cli.py` line 29

#### 4. LIKE wildcard `%` not escaped

`_qbo_escape()` only doubled single quotes. User input containing `%` would expand unintended LIKE patterns in fuzzy search queries.

**Fix:** Strip `%` from escaped values:

```python
def _qbo_escape(value: str) -> str:
    return value.replace("'", "''").replace("%", "")
```

**Location:** `qbo_cli/cli.py` lines 52-55

#### 5. O(n²) in account tree operations

`build_children()`, `count_descendants()`, and `_find_gl_section()` each scanned full lists per recursive call. At 500+ accounts, this causes seconds of delay.

**Fix:** Pre-build lookup dicts:

```python
# Account tree: O(n) preprocessing, O(subtree) traversal
children_by_parent = defaultdict(list)
for a in all_accts:
    pr = a.get("ParentRef", {})
    if isinstance(pr, dict) and pr.get("value"):
        children_by_parent[pr["value"]].append(a)

# GL sections: O(1) lookup via flat index
def _build_section_index(sections):
    index = {}
    for s in sections:
        index[s.name] = s
        index.update(_build_section_index(s.children))
    return index
```

**Location:** `qbo_cli/cli.py` lines 646-662 (index), 705-724 (tree), 733-741 (list)

#### 6. CI actions pinned to mutable tags

`actions/checkout@v4` etc. can be silently updated. Especially risky for `publish.yml` which has `id-token: write` for PyPI trusted publishing.

**Fix:** Pin to immutable commit SHAs:

```yaml
- uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4
- uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5
- uses: pypa/gh-action-pypi-publish@ed0c53931b1dc9bd32cbe73a98c7f6766f8a527e  # release/v1
```

**Location:** `.github/workflows/lint.yml`, `.github/workflows/publish.yml`

## Prevention Strategies

| Issue | Prevention | Automated Check |
|-------|-----------|----------------|
| Version drift | Import from single source | CI: compare pyproject.toml vs `__init__.py` |
| Python compat | `from __future__ import annotations` | Add `UP` rules to ruff; CI matrix with 3.9 |
| OAuth CSRF | Document as security invariant | Unit test with wrong state → assert error |
| Lock permissions | Pattern: always chmod after lock create | Grep for `open(.*lock` without `chmod` |
| LIKE wildcards | Escape in `_qbo_escape` | Unit test for `_qbo_escape("50%")` |
| O(n²) tree ops | Pre-built dicts before recursion | Benchmark test with 500+ accounts |
| Mutable CI tags | Pin to SHAs | `rg 'uses:.*@[v0-9]' .github/workflows/` → fail |

## Remaining (P3 — not yet fixed)

- `007`: Dead `elif e_clean` branch in `_format_date_range`
- `008`: `GLSection` tree properties not memoized (`cached_property`)
- `009`: `import calendar` deferred inside function body

## Cross-References

- Session notes: `03_notes/2026-02-17-review-p1p2-fixes.md`
- Initial bugfix: `03_notes/2026-02-17-bugfix-version-and-py39-compat.md`
- Todo files: `todos/001-complete-p1-*` through `todos/009-pending-p3-*`
- Commits: `23452e3`, `9cf3825`
