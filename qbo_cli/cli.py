#!/usr/bin/env python3
"""qbo-cli — Command-line interface for QuickBooks Online API.

A single-file CLI for interacting with the QuickBooks Online (QBO) API.
Supports OAuth 2.0 authentication, querying entities with auto-pagination,
CRUD operations, financial reports, and raw API access.

Homepage: https://github.com/alexph-dev/qbo-cli
License: MIT
"""

from __future__ import annotations

import argparse
import fcntl
import functools
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from qbo_cli import __version__
from qbo_cli.cli_options import (
    _build_report_params,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _emit_result,
    _parse_date,
    _read_optional_stdin_json,
    _read_stdin_json,
    _resolve_fmt,
)
from qbo_cli.constants import (
    AUTH_URL,
    CONFIG_PATH,
    DEFAULT_MAX_PAGES,
    DEFAULT_REDIRECT,
    FMT_HELP,
    GL_OUTPUT_FORMATS,
    MAX_RESULTS,
    MINOR_VERSION,
    OUTPUT_FORMATS,
    PROD_BASE,
    PROFILE_RE,
    QBO_DIR,
    REFRESH_EXPIRY_WARN_DAYS,
    REFRESH_MARGIN_SEC,
    REPORT_WIDTH,
    SANDBOX_BASE,
    SCOPE,
    TOKEN_URL,
)
from qbo_cli.errors import die, err_print
from qbo_cli.output import (
    _first_list_value,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _format_amount,
    _format_date_range,
    _has_nested_dict_list,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _is_month_end,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _is_month_start,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _normalize_output_data,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _output_kv,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _pad_line,
    _truncate,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _unwrap_entity_dict,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    output,
    output_text,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    output_tsv,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
)
from qbo_cli.qbo_query import _qbo_escape
from qbo_cli.report_registry import (
    _REPORT_ALIAS_MAP,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    REPORT_REGISTRY,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _format_report_list,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _resolve_report_name,
)

# ─── Config ──────────────────────────────────────────────────────────────────


class Config:
    """Load config from env vars → profiled config file → defaults."""

    def __init__(self, profile: str = "prod"):
        profile = profile.lower()
        if not PROFILE_RE.match(profile):
            die(f"Invalid profile name '{profile}'. Use only letters, digits, hyphens, underscores.")
        self.profile: str = profile
        self.client_id: str = ""
        self.client_secret: str = ""
        self.redirect_uri: str = DEFAULT_REDIRECT
        self.realm_id: str = ""
        self.sandbox: bool = False
        self._load()

    @property
    def tokens_path(self) -> Path:
        """Per-profile token file path."""
        return QBO_DIR / f"tokens.{self.profile}.json"

    def _load(self):
        qbo_sandbox = os.environ.get("QBO_SANDBOX", "")
        if qbo_sandbox.lower() in ("1", "true", "yes"):
            die("QBO_SANDBOX is no longer supported. Use QBO_PROFILE=dev instead.")

        file_cfg: dict = {}
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text())
            except json.JSONDecodeError:
                err_print("Warning: ~/.qbo/config.json is not valid JSON, ignoring.")
                raw = {}

            if "client_id" in raw:
                err_print(
                    "Warning: ~/.qbo/config.json uses legacy flat format.\n"
                    "  Run 'qbo auth setup' to migrate to profiled format."
                )
            else:
                file_cfg = raw.get(self.profile, {})

        self.client_id = os.environ.get("QBO_CLIENT_ID", file_cfg.get("client_id", ""))
        self.client_secret = os.environ.get("QBO_CLIENT_SECRET", file_cfg.get("client_secret", ""))
        self.redirect_uri = os.environ.get("QBO_REDIRECT_URI", file_cfg.get("redirect_uri", DEFAULT_REDIRECT))
        self.realm_id = os.environ.get("QBO_REALM_ID", file_cfg.get("realm_id", ""))
        self.sandbox = file_cfg.get("sandbox", False)
        if isinstance(self.sandbox, str):
            self.sandbox = self.sandbox.lower() in ("1", "true", "yes")

    def validate(self):
        """Raise if missing required config."""
        if not self.client_id or not self.client_secret:
            die(
                f"Missing QBO credentials for profile '{self.profile}'. Run setup first:\n"
                f"  qbo --profile {self.profile} auth setup\n\n"
                "Or set environment variables:\n"
                "  export QBO_CLIENT_ID='your-client-id'\n"
                "  export QBO_CLIENT_SECRET='your-client-secret'\n\n"
                "Or create ~/.qbo/config.json (see config.json.example in repo)."
            )


# ─── Token Manager ───────────────────────────────────────────────────────────


class TokenManager:
    """Thread-safe, file-locked token storage with auto-refresh."""

    def __init__(self, config: Config):
        self.config = config
        self._tokens: dict | None = None

    def load(self) -> dict:
        """Load tokens from disk."""
        tp = self.config.tokens_path
        if not tp.exists():
            # Auto-migrate legacy tokens.json for prod profile
            legacy = QBO_DIR / "tokens.json"
            if self.config.profile == "prod" and legacy.exists():
                legacy.rename(tp)
                os.chmod(tp, 0o600)
                err_print(f"Migrated {legacy} -> {tp}")
            else:
                die(f"No tokens found for profile '{self.config.profile}'. Run: qbo auth init")
        try:
            tokens = json.loads(tp.read_text())
        except json.JSONDecodeError:
            die(f"Token file corrupted. Delete {tp} and re-run: qbo auth init")
        self._tokens = tokens
        return tokens

    def save(self, tokens: dict):
        """Atomic write: temp file → rename. Permissions set before rename."""
        tp = self.config.tokens_path
        QBO_DIR.mkdir(parents=True, exist_ok=True)
        QBO_DIR.chmod(0o700)
        tmp = tp.with_suffix(".tmp")
        tmp.write_text(json.dumps(tokens, indent=2))
        tmp.chmod(0o600)  # set permissions BEFORE rename to avoid exposure window
        tmp.rename(tp)
        self._tokens = tokens

    def get_valid_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        tokens = self.load()
        self._warn_refresh_expiry(tokens)
        expires_at = tokens.get("expires_at", 0)

        if time.time() < expires_at - REFRESH_MARGIN_SEC:
            return tokens["access_token"]

        return self._locked_refresh(tokens)

    def _warn_refresh_expiry(self, tokens: dict):
        """Warn to stderr if refresh token is nearing expiry."""
        refresh_exp = tokens.get("refresh_expires_at", 0)
        days_left = (refresh_exp - time.time()) / 86400
        if 0 < days_left < REFRESH_EXPIRY_WARN_DAYS:
            err_print(
                f"⚠ Refresh token expires in {days_left:.1f} days. "
                f"Run 'qbo auth init' to re-authorize before it expires."
            )

    def _locked_refresh(self, tokens: dict) -> str:
        """Refresh with exclusive file lock to prevent concurrent refresh."""
        lock_path = self.config.tokens_path.with_suffix(".lock")
        QBO_DIR.mkdir(parents=True, exist_ok=True)

        with open(lock_path, "w") as lock_file:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                # Re-read — another process may have refreshed
                current = self.load()
                if time.time() < current["expires_at"] - REFRESH_MARGIN_SEC:
                    return current["access_token"]

                new_tokens = self._do_refresh(current)
                self.save(new_tokens)
                return new_tokens["access_token"]
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _do_refresh(self, tokens: dict) -> dict:
        """Call Intuit token endpoint to refresh."""
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                },
                auth=(self.config.client_id, self.config.client_secret),
                timeout=30,
            )
        except requests.ConnectionError:
            die("Network error during token refresh. Check your connection.")
        except requests.Timeout:
            die("Timeout during token refresh. Intuit OAuth may be down.")

        if resp.status_code == 400:
            try:
                body = resp.json()
            except ValueError:
                die(f"Token refresh failed (400): {resp.text[:500]}")
            if body.get("error") == "invalid_grant":
                die(
                    "Refresh token expired or revoked.\n"
                    "Re-authorize: qbo auth init\n"
                    "This happens if the token wasn't refreshed within 100 days."
                )
            die(f"Token refresh failed: {body.get('error', 'unknown')} — {body.get('error_description', '')}")

        if not resp.ok:
            die(f"Token refresh failed (HTTP {resp.status_code}): {resp.text[:500]}")

        data = resp.json()

        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": time.time() + data["expires_in"],
            "refresh_expires_at": time.time() + data.get("x_refresh_token_expires_in", 8640000),
            "realm_id": tokens.get("realm_id", self.config.realm_id),
            "token_type": data.get("token_type", "bearer"),
            "created_at": tokens.get("created_at", time.time()),
            "refreshed_at": time.time(),
        }

    def exchange_code(self, auth_code: str, realm_id: str) -> dict:
        """Exchange authorization code for tokens."""
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "redirect_uri": self.config.redirect_uri,
                },
                auth=(self.config.client_id, self.config.client_secret),
                timeout=30,
            )
        except requests.ConnectionError:
            die("Network error during code exchange. Check your connection.")
        except requests.Timeout:
            die("Timeout during code exchange. Intuit OAuth may be down.")

        if not resp.ok:
            die(f"Code exchange failed (HTTP {resp.status_code}): {resp.text[:500]}")

        data = resp.json()

        tokens = {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "expires_at": time.time() + data["expires_in"],
            "refresh_expires_at": time.time() + data.get("x_refresh_token_expires_in", 8640000),
            "realm_id": realm_id,
            "token_type": data.get("token_type", "bearer"),
            "created_at": time.time(),
            "refreshed_at": time.time(),
        }
        self.save(tokens)
        return tokens


# ─── QBO Client ──────────────────────────────────────────────────────────────


class QBOClient:
    """QuickBooks Online API client with auto-refresh and retry."""

    def __init__(self, config: Config, token_mgr: TokenManager):
        self.config = config
        self.token_mgr = token_mgr

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _base_url(self) -> str:
        tokens = self.token_mgr._tokens or self.token_mgr.load()
        realm = tokens.get("realm_id") or self.config.realm_id
        if not realm:
            die("No realm_id. Set QBO_REALM_ID or run qbo auth init.")
        base = SANDBOX_BASE if self.config.sandbox else PROD_BASE
        return f"{base}/{realm}"

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
        raw_response: bool = False,
    ):
        """Make API request with auto-refresh and 401 retry."""
        token = self.token_mgr.get_valid_token()
        url = f"{self._base_url()}/{path}"

        # Always include minorversion for consistent API behavior
        if params is None:
            params = {}
        params.setdefault("minorversion", MINOR_VERSION)

        for attempt in range(2):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=self._headers(token),
                    params=params,
                    json=json_body,
                    timeout=60,
                )
            except requests.ConnectionError:
                die("Network error connecting to QBO API. Check your connection.")
            except requests.Timeout:
                die("QBO API request timed out (60s). Try again later.")

            if resp.status_code == 401 and attempt == 0:
                err_print("Got 401, forcing token refresh...")
                token = self.token_mgr._locked_refresh(self.token_mgr.load())
                continue

            break

        if raw_response:
            return resp

        if not resp.ok:
            # Try to extract QBO Fault message for better error reporting
            error_detail = resp.text[:500]
            try:
                error_json = resp.json()
                fault = error_json.get("Fault", {})
                errors = fault.get("Error", [])
                if errors:
                    error_detail = "; ".join(f"{e.get('Message', '')} — {e.get('Detail', '')}" for e in errors)
            except (ValueError, AttributeError):
                pass
            err_print(f"API error {resp.status_code}: {error_detail}")
            sys.exit(1)

        return resp.json()

    def query(self, sql: str, max_pages: int = DEFAULT_MAX_PAGES) -> list:
        """Run QBO query with auto-pagination."""

        def _extract_entities(data: dict) -> list:
            qr = data.get("QueryResponse", {})
            for key, val in qr.items():
                if isinstance(val, list):
                    return val
            return []

        # If user specifies MAXRESULTS or STARTPOSITION explicitly, honor it and skip auto-pagination
        if re.search(r"\bMAXRESULTS\b", sql, re.IGNORECASE) or re.search(r"\bSTARTPOSITION\b", sql, re.IGNORECASE):
            data = self.request("GET", "query", params={"query": sql})
            return _extract_entities(data)

        all_results = []
        start = 1

        for page in range(max_pages):
            paginated_sql = f"{sql} STARTPOSITION {start} MAXRESULTS {MAX_RESULTS}"
            data = self.request("GET", "query", params={"query": paginated_sql})

            entities = _extract_entities(data)
            all_results.extend(entities)

            if len(entities) < MAX_RESULTS:
                break
            start += MAX_RESULTS

        return all_results

    def get(self, entity: str, entity_id: str) -> dict:
        return self.request("GET", f"{entity.lower()}/{entity_id}")

    def create(self, entity: str, body: dict) -> dict:
        return self.request("POST", entity.lower(), json_body=body)

    def update(self, entity: str, body: dict) -> dict:
        return self.request("POST", entity.lower(), json_body=body)

    def delete(self, entity: str, entity_id: str) -> dict:
        current = self.get(entity, entity_id)
        entity_data = current.get(entity, current)
        return self.request("POST", entity.lower(), params={"operation": "delete"}, json_body=entity_data)

    def void(self, entity: str, entity_id: str) -> dict:
        """Void a transaction by ID (GET for SyncToken, then POST with operation=void)."""
        current = self.get(entity, entity_id)
        entity_data = current.get(entity, current)
        return self.request("POST", entity.lower(), params={"operation": "void"}, json_body=entity_data)

    def report(self, report_type: str, params: dict | None = None) -> dict:
        return self.request("GET", f"reports/{report_type}", params=params)

    def raw(self, method: str, path: str, body: dict | None = None) -> dict:
        return self.request(method.upper(), path, json_body=body)


# ─── GL Report Engine ────────────────────────────────────────────────────────


class GLTransaction:
    """A single GL transaction."""

    __slots__ = ("date", "txn_type", "txn_id", "num", "customer", "memo", "account", "amount")

    def __init__(self, date="", txn_type="", txn_id="", num="", customer="", memo="", account="", amount=0.0):
        self.date = date
        self.txn_type = txn_type
        self.txn_id = txn_id
        self.num = num
        self.customer = customer
        self.memo = memo
        self.account = account
        self.amount = amount


class GLSection:
    """Parsed GL account section with amounts and sub-sections."""

    def __init__(self, name: str, acct_id: str = ""):
        self.name = name
        self.id = acct_id
        self.direct_amount = 0.0
        self.direct_count = 0
        self.children: list["GLSection"] = []
        self.transactions: list[GLTransaction] = []

    @functools.cached_property
    def total_amount(self) -> float:
        return self.direct_amount + sum(c.total_amount for c in self.children)

    @functools.cached_property
    def total_count(self) -> int:
        return self.direct_count + sum(c.total_count for c in self.children)

    @functools.cached_property
    def all_transactions(self) -> list[GLTransaction]:
        """All transactions including from sub-sections."""
        txns = list(self.transactions)
        for c in self.children:
            txns.extend(c.all_transactions)
        return txns


def _parse_txn_from_row(cols: list[dict]) -> GLTransaction | None:
    """Parse a Data row's ColData into a GLTransaction."""
    if not cols or cols[0].get("value", "") == "Beginning Balance":
        return None
    amt_str = cols[6].get("value", "") if len(cols) > 6 else ""
    if not amt_str:
        return None
    try:
        amount = float(amt_str)
    except ValueError:
        return None
    return GLTransaction(
        date=cols[0].get("value", "") if len(cols) > 0 else "",
        txn_type=cols[1].get("value", "") if len(cols) > 1 else "",
        txn_id=cols[1].get("id", "") if len(cols) > 1 else "",
        num=cols[2].get("value", "") if len(cols) > 2 else "",
        customer=cols[3].get("value", "") if len(cols) > 3 else "",
        memo=cols[4].get("value", "") if len(cols) > 4 else "",
        account=cols[5].get("value", "") if len(cols) > 5 else "",
        amount=amount,
    )


def _parse_gl_rows(rows_obj: dict) -> list[GLSection]:
    """Parse GL Rows object into list of GLSection."""
    sections: list[GLSection] = []
    if not rows_obj or "Row" not in rows_obj:
        return sections

    for row in rows_obj["Row"]:
        if row.get("type") != "Section":
            continue

        header_cols = row.get("Header", {}).get("ColData", [])
        name = header_cols[0].get("value", "").strip() if header_cols else ""
        acct_id = header_cols[0].get("id", "") if header_cols else ""

        if not name:
            placeholder = GLSection("__direct__", acct_id)
            inner_rows = row.get("Rows", {})
            if inner_rows and "Row" in inner_rows:
                for inner_row in inner_rows["Row"]:
                    if inner_row.get("type") == "Data":
                        txn = _parse_txn_from_row(inner_row.get("ColData", []))
                        if txn:
                            placeholder.direct_amount += txn.amount
                            placeholder.direct_count += 1
                            placeholder.transactions.append(txn)
            sections.append(placeholder)
            continue

        section = GLSection(name, acct_id)
        inner_rows = row.get("Rows", {})

        if inner_rows and "Row" in inner_rows:
            for inner_row in inner_rows["Row"]:
                if inner_row.get("type") == "Data":
                    txn = _parse_txn_from_row(inner_row.get("ColData", []))
                    if txn:
                        section.direct_amount += txn.amount
                        section.direct_count += 1
                        section.transactions.append(txn)

        section.children = _parse_gl_rows(inner_rows)
        absorbed = [c for c in section.children if c.name == "__direct__"]
        for a in absorbed:
            section.direct_amount += a.direct_amount
            section.direct_count += a.direct_count
            section.transactions.extend(a.transactions)
        section.children = [c for c in section.children if c.name != "__direct__"]

        sections.append(section)

    return sections


def _build_section_index(sections: list[GLSection]) -> dict[str, GLSection]:
    """Build flat name/id→section dict for O(1) lookups.

    Keys by both name and id to handle name collisions across hierarchy levels."""
    index = {}
    for s in sections:
        index[s.name] = s
        if s.id:
            index[s.id] = s
        index.update(_build_section_index(s.children))
    return index


def _find_gl_section(section_idx: dict[str, GLSection], name: str, acct_id: str = "") -> GLSection | None:
    """Find a GL section by id (preferred) or name, with suffix-match fallback."""
    if acct_id and acct_id in section_idx:
        return section_idx[acct_id]
    if name in section_idx:
        return section_idx[name]
    for key in section_idx:
        if key.endswith(f" {name}"):
            return section_idx[key]
    return None


def _extract_dates_from_gl(gl_data: dict) -> tuple[str | None, str | None]:
    """Extract earliest and latest transaction dates from raw GL data."""
    dates = []

    def walk(rows_obj):
        if not rows_obj or "Row" not in rows_obj:
            return
        for row in rows_obj["Row"]:
            if row.get("type") == "Data":
                cols = row.get("ColData", [])
                if cols:
                    val = cols[0].get("value", "")
                    if len(val) == 10 and val[4] == "-" and val[7] == "-":
                        dates.append(val)
            elif row.get("type") == "Section":
                walk(row.get("Rows", {}))

    walk(gl_data.get("Rows", {}))
    if not dates:
        return None, None
    dates.sort()
    return dates[0], dates[-1]


def _discover_account_tree(client: "QBOClient", account_ref: str) -> dict:
    """Build account tree from QBO by fetching sub-accounts under a parent.
    account_ref can be a numeric ID or account name (fuzzy match).
    """
    if account_ref.isdigit():
        parent_id = account_ref
        safe_ref = _qbo_escape(account_ref)
        accts = client.query(f"SELECT Id, Name, FullyQualifiedName FROM Account WHERE Id = '{safe_ref}'")
        parent_name = (
            accts[0].get("FullyQualifiedName", accts[0].get("Name", f"Account {account_ref}"))
            if accts
            else f"Account {account_ref}"
        )
    else:
        safe_ref = _qbo_escape(account_ref)
        accts = client.query(f"SELECT Id, Name, FullyQualifiedName FROM Account WHERE Name LIKE '%{safe_ref}%'")
        if not accts:
            die(f"No account found matching '{account_ref}'")
        match = next((a for a in accts if a["Name"].lower() == account_ref.lower()), accts[0])
        parent_id = match["Id"]
        parent_name = match.get("FullyQualifiedName", match["Name"])

    all_accts = client.query("SELECT Id, Name, FullyQualifiedName, SubAccount, ParentRef FROM Account")

    children_by_parent = defaultdict(list)
    for a in all_accts:
        pr = a.get("ParentRef", {})
        if isinstance(pr, dict) and pr.get("value"):
            children_by_parent[pr["value"]].append(a)

    def build_children(pid: str) -> list[dict]:
        kids = [
            {"name": a["Name"], "id": a["Id"], "children": build_children(a["Id"])} for a in children_by_parent[pid]
        ]
        kids.sort(key=lambda x: x["name"])
        return kids

    return {
        "name": parent_name.split(":")[-1].strip(),
        "id": parent_id,
        "children": build_children(parent_id),
    }


def _list_all_accounts_data(client: "QBOClient") -> dict:
    """Return all top-level accounts grouped by type."""
    all_accts = client.query("SELECT Id, Name, FullyQualifiedName, AccountType, SubAccount, ParentRef FROM Account")

    children_by_parent = defaultdict(list)
    for a in all_accts:
        pr = a.get("ParentRef", {})
        if isinstance(pr, dict) and pr.get("value"):
            children_by_parent[pr["value"]].append(a)

    def count_descendants(pid: str) -> int:
        return sum(1 + count_descendants(a["Id"]) for a in children_by_parent[pid])

    top = [a for a in all_accts if not a.get("SubAccount", False)]
    top.sort(key=lambda a: (a.get("AccountType", ""), a.get("Name", "")))

    groups = []
    current_group = None
    for a in top:
        atype = a.get("AccountType", "Other")
        desc = count_descendants(a["Id"])
        if current_group is None or current_group["type"] != atype:
            current_group = {"type": atype, "accounts": []}
            groups.append(current_group)
        current_group["accounts"].append(
            {
                "id": a["Id"],
                "name": a["Name"],
                "sub_account_count": desc,
            }
        )

    return {
        "groups": groups,
        "top_level_count": len(top),
        "total_count": len(all_accts),
    }


def _list_all_accounts(client: "QBOClient") -> None:
    """Print all top-level accounts grouped by type."""
    account_data = _list_all_accounts_data(client)
    for index, group in enumerate(account_data["groups"]):
        if index > 0:
            print()
        print(f"── {group['type']} ──")
        for account in group["accounts"]:
            desc = account["sub_account_count"]
            sub_str = f"  ({desc} sub-accounts)" if desc else ""
            print(f"  {account['id']:>15}  {account['name']}{sub_str}")

    print(f"\n{account_data['top_level_count']} top-level accounts, {account_data['total_count']} total")


def _print_account_tree(node: dict, indent: int = 0):
    """Print account tree."""
    prefix = "  " * indent
    marker = "└─ " if indent > 0 else ""
    print(f"{prefix}{marker}{node['name']} (ID: {node['id']})")
    for child in node["children"]:
        _print_account_tree(child, indent + 1)


def _resolve_customer(client: "QBOClient", name: str) -> tuple[str, str]:
    """Resolve customer display name to (id, full_name)."""
    if name.isdigit():
        data = client.get("Customer", name)
        cust = data.get("Customer", data)
        return name, cust.get("FullyQualifiedName", cust.get("DisplayName", name))

    # Exact then fuzzy
    safe_name = _qbo_escape(name)
    customers = client.query(
        f"SELECT Id, DisplayName, FullyQualifiedName FROM Customer WHERE DisplayName = '{safe_name}'"
    )
    if not customers:
        customers = client.query(
            f"SELECT Id, DisplayName, FullyQualifiedName FROM Customer WHERE DisplayName LIKE '%{safe_name}%'"
        )
    if not customers:
        die(f"No customer found matching '{name}'")
    if len(customers) > 1:
        err_print(f"Multiple customers found for '{name}':")
        for c in customers:
            err_print(f"  ID={c['Id']}  Name={c.get('FullyQualifiedName', c['DisplayName'])}")
        err_print("Using first match.")
    for c in customers:
        if c.get("DisplayName", "").lower() == name.lower():
            return c["Id"], c.get("FullyQualifiedName", c["DisplayName"])
    c = customers[0]
    return c["Id"], c.get("FullyQualifiedName", c["DisplayName"])


def _compute_subtotal(section_idx: dict[str, GLSection], node: dict) -> tuple[float, int]:
    """Compute total for a tree node (own + children, recursively)."""
    if not node["children"]:
        section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
        if section:
            return section.total_amount, section.total_count
        return 0.0, 0

    section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
    total_amt = section.direct_amount if section else 0.0
    total_cnt = section.direct_count if section else 0
    for child in node["children"]:
        c_amt, c_cnt = _compute_subtotal(section_idx, child)
        total_amt += c_amt
        total_cnt += c_cnt
    return total_amt, total_cnt


def _build_report_lines(
    section_idx: dict[str, GLSection],
    node: dict,
    currency: str,
    indent: int = 0,
    lines: list | None = None,
    expanded: bool = False,
) -> list[str]:
    if lines is None:
        lines = []

    prefix = "  " * indent
    subtotal_amt, subtotal_cnt = _compute_subtotal(section_idx, node)

    if not node["children"]:
        section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
        amt = section.total_amount if section else 0.0
        cnt = section.total_count if section else 0
        if cnt == 0 and not amt:
            return lines
        lines.append(_pad_line(f"{node['name']} ({cnt})", _format_amount(amt, currency), prefix))
        if expanded and section:
            _append_txn_lines(section.all_transactions, currency, indent + 1, lines)
    else:
        if subtotal_cnt == 0 and not subtotal_amt:
            return lines

        section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
        own_cnt = section.direct_count if section else 0
        own_amt = section.direct_amount if section else 0.0
        if own_cnt > 0:
            lines.append(_pad_line(f"{node['name']} ({own_cnt})", _format_amount(own_amt, currency), prefix))
            if expanded and section:
                _append_txn_lines(section.transactions, currency, indent + 1, lines)
        else:
            lines.append(f"{prefix}{node['name']}")

        for child in node["children"]:
            _build_report_lines(section_idx, child, currency, indent + 1, lines, expanded=expanded)

        lines.append(_pad_line(f"Total for {node['name']}", _format_amount(subtotal_amt, currency), prefix))

    return lines


def _append_txn_lines(txns: list[GLTransaction], currency: str, indent: int, lines: list[str]):
    """Append formatted transaction lines."""
    for t in sorted(txns, key=lambda x: x.date):
        prefix = "  " * indent
        memo = t.memo[:40] + "…" if len(t.memo) > 40 else t.memo
        label = f"{t.date}  {t.txn_type:<12s} {memo}"
        lines.append(_pad_line(label, _format_amount(t.amount, currency), prefix))


def _build_txns_report(section_idx: dict[str, GLSection], node: dict, currency: str) -> list[str]:
    """Flat list of all transactions sorted by date."""
    section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
    if not section:
        return ["(no transactions)"]

    txns = section.all_transactions
    if not txns:
        return ["(no transactions)"]

    txns.sort(key=lambda t: t.date)

    lines = []
    # Header
    lines.append(f"{'Date':<12s} {'Type':<14s} {'Amount':>14s}  {'Account'}")
    lines.append("─" * REPORT_WIDTH)

    for t in txns:
        acct_short = t.account.split(":")[-1] if t.account else ""
        amt_str = _format_amount(t.amount, currency)
        lines.append(f"{t.date:<12s} {t.txn_type:<14s} {amt_str:>14s}  {acct_short}")
        if t.memo:
            memo = t.memo[:68] + "…" if len(t.memo) > 68 else t.memo
            lines.append(f"{'':12s} {memo}")

    lines.append("─" * REPORT_WIDTH)
    total = sum(t.amount for t in txns)
    lines.append(f"{'TOTAL':<12s} {'':14s} {_format_amount(total, currency):>14s}  ({len(txns)} transactions)")

    return lines


def _collapse_tree(node: dict) -> dict:
    """Collapse a tree to a single node (no children) for --no-sub mode."""
    return {"name": node["name"], "id": node["id"], "children": []}


def _build_by_customer_report(
    section_idx: dict[str, GLSection], node: dict, currency: str, customer_filter: str = "", sort_by: str = "alpha"
) -> list[str]:
    """Group all transactions by customer and show per-customer subtotals.

    customer_filter: if set, group at depth=1 below this customer prefix
                     (e.g. "Parent" groups Parent:Team:Leaf → Parent:Team, skips Parent itself)
    sort_by: "alpha" (alphabetical) or "amount" (absolute total descending)
    """

    section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
    if not section:
        return ["(no transactions)"]

    txns = section.all_transactions
    if not txns:
        return ["(no transactions)"]

    # Determine grouping key for each transaction
    prefix = customer_filter.rstrip(":") + ":" if customer_filter else ""

    groups: dict[str, list[GLTransaction]] = defaultdict(list)
    skipped_parent_txns = []

    for t in txns:
        cust = t.customer or "(no customer)"

        if prefix:
            if cust == customer_filter.rstrip(":"):
                # Direct transactions on the parent itself — skip from groups
                skipped_parent_txns.append(t)
                continue
            if cust.startswith(prefix):
                # Extract first child level: Parent:Team:Leaf → Parent:Team
                remainder = cust[len(prefix) :]
                first_child = remainder.split(":")[0]
                group_key = prefix + first_child
                groups[group_key].append(t)
            else:
                # Doesn't match filter — include as-is
                groups[cust].append(t)
        else:
            groups[cust].append(t)

    # Sort
    if sort_by == "amount":
        sorted_custs = sorted(groups.keys(), key=lambda c: abs(sum(t.amount for t in groups[c])), reverse=True)
    else:
        sorted_custs = sorted(groups.keys())

    lines = []
    lines.append(node["name"])
    lines.append("")

    for cust in sorted_custs:
        ctxns = groups[cust]
        total = sum(t.amount for t in ctxns)
        lines.append(_pad_line(f"{cust} ({len(ctxns)})", _format_amount(total, currency)))

    # Show parent's direct transactions if any
    if skipped_parent_txns:
        total = sum(t.amount for t in skipped_parent_txns)
        lines.append("")
        lines.append(
            _pad_line(f"({customer_filter} direct) ({len(skipped_parent_txns)})", _format_amount(total, currency))
        )

    lines.append("")
    grand_total = sum(t.amount for t in txns)
    lines.append(_pad_line(f"TOTAL ({len(txns)})", _format_amount(grand_total, currency)))

    return lines


def _txn_to_dict(t: GLTransaction) -> dict:
    """Serialize a GLTransaction to a plain dict."""
    return {
        "date": t.date,
        "type": t.txn_type,
        "id": t.txn_id,
        "num": t.num,
        "customer": t.customer,
        "memo": t.memo,
        "account": t.account,
        "amount": t.amount,
    }


def cmd_gl_report(args, config, token_mgr):
    """Generate a hierarchical General Ledger report."""
    client = QBOClient(config, token_mgr)
    out_mode = _resolve_fmt(args)

    # --list-accounts mode
    if args.list_accounts:
        if out_mode not in ("text", "json"):
            die("gl-report --list-accounts supports text or json output only.")
        if args.account:
            tree = _discover_account_tree(client, args.account)
            if out_mode == "json":
                output(tree, out_mode)
            else:
                _print_account_tree(tree)
        else:
            if out_mode == "json":
                output(_list_all_accounts_data(client), out_mode)
            else:
                _list_all_accounts(client)
        return

    # Resolve customer (optional)
    cust_id, cust_name = None, None
    if args.customer:
        cust_id, cust_name = _resolve_customer(client, args.customer)

    # Resolve dates
    end_date = _parse_date(args.end) if args.end else datetime.now().strftime("%Y-%m-%d")
    start_date = _parse_date(args.start) if args.start else "2000-01-01"
    auto_start = args.start is None

    # Resolve account tree
    if args.account:
        account_tree = _discover_account_tree(client, args.account)
    else:
        die("Account is required. Use -a/--account (ID or name). Use --list-accounts to explore.")

    # Fetch GL
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "accounting_method": args.method,
    }
    if cust_id:
        params["customer"] = cust_id
    gl_data = client.report("GeneralLedger", params)

    # Check for no data
    for opt in gl_data.get("Header", {}).get("Option", []):
        if opt.get("Name") == "NoReportData" and opt.get("Value") == "true":
            die("No data found for the specified filters.")

    gl_sections = _parse_gl_rows(gl_data.get("Rows", {}))
    section_idx = _build_section_index(gl_sections)

    # Collapse tree if --no-sub
    if args.no_sub:
        account_tree = _collapse_tree(account_tree)

    # Auto-detect start date
    display_start = start_date
    if auto_start:
        actual_first, _ = _extract_dates_from_gl(gl_data)
        if actual_first:
            display_start = actual_first

    # Output
    if out_mode == "tsv":
        die("gl-report does not support tsv output. Use text, json, txns, or expanded.")
    title = f"General Ledger Report - {cust_name}" if cust_name else "General Ledger Report"
    date_range = _format_date_range(display_start, end_date)
    currency = args.currency
    total_amt, _ = _compute_subtotal(section_idx, account_tree)

    if args.by_customer and out_mode in ("json", "txns"):
        err_print("Warning: --by-customer is only supported with text/expanded output. Ignoring -g flag.")

    if out_mode == "json":

        def tree_to_dict(node):
            section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
            result = {"name": node["name"], "id": node["id"]}
            if not node["children"]:
                result["amount"] = section.total_amount if section else 0.0
                result["count"] = section.total_count if section else 0
                txns = section.all_transactions if section else []
                if txns:
                    result["transactions"] = [_txn_to_dict(t) for t in sorted(txns, key=lambda x: x.date)]
            else:
                result["direct_amount"] = section.direct_amount if section else 0.0
                result["direct_count"] = section.direct_count if section else 0
                amt, cnt = _compute_subtotal(section_idx, node)
                result["total_amount"] = amt
                result["total_count"] = cnt
                result["children"] = [tree_to_dict(c) for c in node["children"]]
                if section and section.transactions:
                    result["transactions"] = [
                        _txn_to_dict(t) for t in sorted(section.transactions, key=lambda x: x.date)
                    ]
            return result

        report_data = {
            "start_date": display_start,
            "end_date": end_date,
            "method": args.method,
            "account": tree_to_dict(account_tree),
            "total": total_amt,
        }
        if cust_name:
            report_data["customer"] = cust_name
            report_data["customer_id"] = cust_id

        output(report_data, out_mode)

    elif out_mode == "txns":
        lines = [title, date_range, ""]
        lines.extend(_build_txns_report(section_idx, account_tree, currency))
        print("\n".join(lines))

    elif args.by_customer:
        lines = [title, date_range, ""]
        lines.extend(
            _build_by_customer_report(
                section_idx,
                account_tree,
                currency,
                customer_filter=cust_name or "",
                sort_by=args.sort,
            )
        )
        print("\n".join(lines))

    else:
        # text or expanded
        expanded = out_mode == "expanded"
        lines = [title, date_range, ""]
        _build_report_lines(section_idx, account_tree, currency, indent=0, lines=lines, expanded=expanded)
        lines.append("")
        lines.append(_pad_line("TOTAL", _format_amount(total_amt, currency)))
        print("\n".join(lines))


# ─── Auth Commands ───────────────────────────────────────────────────────────


def cmd_auth_init(args, config, token_mgr):
    """Interactive OAuth authorization flow."""
    config.validate()

    oauth_state = os.urandom(16).hex()
    auth_params = urlencode(
        {
            "client_id": config.client_id,
            "scope": SCOPE,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "state": oauth_state,
        }
    )
    auth_url = f"{AUTH_URL}?{auth_params}"

    if args.manual:
        print(f"Open this URL in a browser:\n\n{auth_url}\n", file=sys.stderr)
        print("After authorizing, paste the full redirect URL here:", file=sys.stderr)
        redirect_url = input().strip()
        parsed = parse_qs(urlparse(redirect_url).query)
        try:
            code = parsed["code"][0]
            realm_id = parsed["realmId"][0]
        except (KeyError, IndexError):
            die("Could not parse code and realmId from the redirect URL.")
        if parsed.get("state", [None])[0] != oauth_state:
            die("OAuth state mismatch — possible CSRF. Try again.")
    else:
        code, realm_id = _run_callback_server(auth_url, config, args.port, oauth_state)

    tokens = token_mgr.exchange_code(code, realm_id)
    err_print(f"✓ Authorized. Realm: {realm_id}")
    err_print(f"  Access token expires: {time.ctime(tokens['expires_at'])}")
    err_print(f"  Refresh token expires: {time.ctime(tokens['refresh_expires_at'])}")


def _run_callback_server(auth_url: str, config: Config, port: int, expected_state: str) -> tuple:
    """Start temp HTTP server, print auth URL, wait for callback."""
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            if qs.get("state", [None])[0] != expected_state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch - possible CSRF. Try again.")
                return
            if "code" in qs:
                result["code"] = qs["code"][0]
                result["realm_id"] = qs["realmId"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<h1>Authorization successful!</h1><p>You can close this tab.</p>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code parameter")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    err_print(f"Open this URL in a browser:\n\n{auth_url}\n")
    err_print(f"Waiting for callback on port {port}... (5 min timeout)")

    server.timeout = 30  # per-request timeout
    deadline = time.time() + 300  # 5 min total deadline
    while "code" not in result:
        if time.time() > deadline:
            server.server_close()
            die("Timed out waiting for OAuth callback (5 min). Try again or use --manual mode.")
        server.handle_request()

    server.server_close()
    return result["code"], result["realm_id"]


def cmd_auth_status(args, config, token_mgr):
    """Show token status for active profile."""
    tokens = token_mgr.load()
    now = time.time()
    access_exp = tokens.get("expires_at", 0)
    refresh_exp = tokens.get("refresh_expires_at", 0)

    info = {
        "profile": config.profile,
        "sandbox": config.sandbox,
        "realm_id": tokens.get("realm_id"),
        "access_token_valid": access_exp > now,
        "access_token_expires": time.ctime(access_exp),
        "access_token_remaining_min": max(0, round((access_exp - now) / 60, 1)),
        "refresh_token_expires": time.ctime(refresh_exp),
        "refresh_token_remaining_days": max(0, round((refresh_exp - now) / 86400, 1)),
        "last_refreshed": time.ctime(tokens.get("refreshed_at", 0)),
    }
    output(info, _resolve_fmt(args))


def cmd_auth_refresh(args, config, token_mgr):
    config.validate()
    token_mgr.load()
    token_mgr._locked_refresh(token_mgr._tokens)
    err_print("✓ Token refreshed successfully")


def cmd_auth_setup(args, config, token_mgr):
    """Interactive config setup — creates/updates ~/.qbo/config.json with profiled format."""
    profile = config.profile
    print(f"QuickBooks Online CLI — Setup (profile: {profile})")
    print("=" * 40)
    print()
    print("You need a QuickBooks app from https://developer.intuit.com")
    print("Go to: Dashboard → Create an app → Get your Client ID & Secret")
    print()

    # Load existing config (full file, all profiles)
    all_profiles: dict = {}
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            raw = {}
        # Detect flat format: preserve old values under 'prod' profile
        if "client_id" in raw:
            err_print("Migrating from legacy flat config to profiled format.")
            all_profiles = {"prod": raw}
        else:
            all_profiles = raw

    existing = all_profiles.get(profile, {})

    def prompt(label: str, key: str, default: str = "", secret: bool = False) -> str:
        current = existing.get(key, default)
        if current and secret:
            display = current[:4] + "..." + current[-4:] if len(current) > 12 else "***"
            hint = f" [{display}]"
        elif current:
            hint = f" [{current}]"
        else:
            hint = ""
        val = input(f"{label}{hint}: ").strip()
        return val if val else current

    client_id = prompt("Client ID", "client_id")
    client_secret = prompt("Client Secret", "client_secret", secret=True)
    redirect_uri = prompt("Redirect URI", "redirect_uri", DEFAULT_REDIRECT)

    if not client_id or not client_secret:
        die("Client ID and Client Secret are required.")

    profile_cfg: dict = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }

    # Preserve existing realm_id if present in this profile
    if existing.get("realm_id"):
        profile_cfg["realm_id"] = existing["realm_id"]
    # Sandbox: preserve existing, or default to True for 'dev' profile
    if existing.get("sandbox"):
        profile_cfg["sandbox"] = existing["sandbox"]
    elif profile == "dev":
        profile_cfg["sandbox"] = True

    all_profiles[profile] = profile_cfg

    # Atomic write
    QBO_DIR.mkdir(parents=True, exist_ok=True)
    QBO_DIR.chmod(0o700)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_profiles, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.rename(CONFIG_PATH)

    print()
    print(f"✓ Config saved to {CONFIG_PATH} (profile: {profile})")
    print()
    print("Next step — authorize with QuickBooks:")
    print(f"  qbo {f'--profile {profile} ' if profile != 'prod' else ''}auth init")
    print()
    print("On a headless server (no browser):")
    print(f"  qbo {f'--profile {profile} ' if profile != 'prod' else ''}auth init --manual")


# ─── Entity Commands ─────────────────────────────────────────────────────────


def _make_client(config, token_mgr) -> QBOClient:
    """Build a client for command handlers.

    Lives in cli.py until `qbo_cli.client` module is extracted; it will move
    into `cli_options.py` in the client-extraction commit.
    """
    return QBOClient(config, token_mgr)


def cmd_query(args, config, token_mgr):
    client = _make_client(config, token_mgr)
    results = client.query(args.sql, max_pages=args.max_pages)
    _emit_result(results, args)


def cmd_search(args, config, token_mgr):
    client = _make_client(config, token_mgr)
    results = client.query(args.sql, max_pages=args.max_pages)

    if args.case_sensitive:
        matches = [row for row in results if args.text in json.dumps(row, default=str, ensure_ascii=False)]
    else:
        needle = args.text.casefold()
        matches = [row for row in results if needle in json.dumps(row, default=str, ensure_ascii=False).casefold()]

    _emit_result(matches, args)


def cmd_get(args, config, token_mgr):
    client = _make_client(config, token_mgr)
    result = client.get(args.entity, args.id)
    _emit_result(result, args)


def cmd_create(args, config, token_mgr):
    body = _read_stdin_json()
    client = _make_client(config, token_mgr)
    result = client.create(args.entity, body)
    _emit_result(result, args)


def cmd_update(args, config, token_mgr):
    body = _read_stdin_json()
    client = _make_client(config, token_mgr)
    result = client.update(args.entity, body)
    _emit_result(result, args)


def cmd_delete(args, config, token_mgr):
    client = _make_client(config, token_mgr)
    result = client.delete(args.entity, args.id)
    _emit_result(result, args)


def cmd_void(args, config, token_mgr):
    client = _make_client(config, token_mgr)
    result = client.void(args.entity, args.id)
    _emit_result(result, args)


def cmd_report(args, config, token_mgr):
    """Run a QBO report by name or alias."""
    if args.list_reports:
        print(_format_report_list())
        return
    if not args.report_type:
        die(f"Report type required.\n\n{_format_report_list()}")
    report_name = _resolve_report_name(args.report_type)
    client = _make_client(config, token_mgr)
    result = client.report(report_name, _build_report_params(args))
    _emit_result(result, args)


def cmd_raw(args, config, token_mgr):
    client = _make_client(config, token_mgr)
    body = None
    if args.method.upper() in ("POST", "PUT"):
        body = _read_optional_stdin_json()
    result = client.raw(args.method, args.path, body)
    _emit_result(result, args)


# ─── CLI Parser ──────────────────────────────────────────────────────────────


def _add_output_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str | None = None,
    choices: tuple[str, ...] = OUTPUT_FORMATS,
    help_text: str = FMT_HELP,
) -> None:
    """Add a shared output-format argument to a subcommand parser."""
    parser.add_argument(
        "-o",
        "--output",
        "--format",
        dest="output",
        choices=choices,
        default=default,
        help=help_text,
    )


def _build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """Build the top-level CLI parser and auth subparser."""
    parser = argparse.ArgumentParser(
        prog="qbo",
        description="QuickBooks Online CLI — query, create, update, delete entities and run reports.",
    )
    parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--format", "-f", choices=OUTPUT_FORMATS, default="text", help="Output format (default: text)")
    parser.add_argument("--profile", "-p", default=None, help="Config profile to use (default: prod)")
    parser.add_argument("--sandbox", action="store_true", help="Use dev profile with sandbox API endpoint")

    subs = parser.add_subparsers(dest="command")

    # ── auth ──
    auth_p = subs.add_parser("auth", help="Authentication commands")
    auth_subs = auth_p.add_subparsers(dest="auth_command")

    init_p = auth_subs.add_parser("init", help="Start OAuth authorization flow")
    init_p.add_argument(
        "--manual", action="store_true", help="Manual mode: paste redirect URL instead of local callback server"
    )
    init_p.add_argument("--port", type=int, default=8844, help="Callback server port (default: 8844)")

    auth_subs.add_parser("status", help="Show token status")
    auth_subs.add_parser("refresh", help="Force token refresh")
    auth_subs.add_parser("setup", help="Interactive config setup (creates ~/.qbo/config.json)")

    # ── query ──
    query_p = subs.add_parser("query", help="Run a QBO query (SQL-like)")
    query_p.add_argument("sql", help='QBO query, e.g. "SELECT * FROM Customer"')
    query_p.add_argument(
        "--max-pages", type=int, default=DEFAULT_MAX_PAGES, help=f"Max pagination pages (default: {DEFAULT_MAX_PAGES})"
    )
    _add_output_arg(query_p)

    # ── search ──
    search_p = subs.add_parser("search", help="Run query, then text-search rows locally")
    search_p.add_argument("sql", help='QBO query, e.g. "SELECT * FROM Customer"')
    search_p.add_argument("text", help="Search text (substring match against each row JSON)")
    search_p.add_argument(
        "--max-pages", type=int, default=DEFAULT_MAX_PAGES, help=f"Max pagination pages (default: {DEFAULT_MAX_PAGES})"
    )
    search_p.add_argument("--case-sensitive", action="store_true", help="Use case-sensitive matching")
    _add_output_arg(search_p)

    # ── get ──
    get_p = subs.add_parser("get", help="Get a single entity by ID")
    get_p.add_argument("entity", help="Entity type (Invoice, Customer, etc.)")
    get_p.add_argument("id", help="Entity ID")
    _add_output_arg(get_p)

    # ── create ──
    create_p = subs.add_parser("create", help="Create an entity (JSON on stdin)")
    create_p.add_argument("entity", help="Entity type")
    _add_output_arg(create_p)

    # ── update ──
    update_p = subs.add_parser("update", help="Update an entity (JSON on stdin)")
    update_p.add_argument("entity", help="Entity type")
    _add_output_arg(update_p)

    # ── delete ──
    delete_p = subs.add_parser("delete", help="Delete an entity by ID")
    delete_p.add_argument("entity", help="Entity type")
    delete_p.add_argument("id", help="Entity ID")
    _add_output_arg(delete_p)

    # ── void ──
    void_p = subs.add_parser("void", help="Void a transaction by ID")
    void_p.add_argument("entity", help="Entity type")
    void_p.add_argument("id", help="Entity ID")
    _add_output_arg(void_p)

    # ── report ──
    report_p = subs.add_parser(
        "report",
        help="Run a QBO report (use --list to see available reports)",
    )
    report_p.add_argument(
        "report_type",
        nargs="?",
        help="Report name or alias (e.g. ProfitAndLoss, PnL, GL). Use --list to see all.",
    )
    report_p.add_argument(
        "--list", dest="list_reports", action="store_true", help="List available reports with aliases"
    )
    report_p.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    report_p.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    report_p.add_argument("--date-macro", help='Date macro (e.g. "Last Month", "This Year")')
    report_p.add_argument("params", nargs="*", help="Extra params as key=value")
    _add_output_arg(report_p)

    # ── raw ──
    raw_p = subs.add_parser("raw", help="Make a raw API request")
    raw_p.add_argument("method", help="HTTP method (GET, POST, PUT, DELETE)")
    raw_p.add_argument("path", help="API path after /v3/company/{realm}/")
    _add_output_arg(raw_p)

    # ── gl-report ──
    gl_p = subs.add_parser(
        "gl-report",
        help="Hierarchical General Ledger report by account & customer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  %(prog)s -c "John Smith" -a 125                    # report for account 125
  %(prog)s -c "John Smith" -a "Revenue" --start 2025-01-01
  %(prog)s -c "John Smith" -a 125 --currency USD     # custom currency prefix
  %(prog)s --list-accounts                            # list all top-level accounts
  %(prog)s -a 125 --list-accounts                     # show sub-account tree""",
    )
    gl_p.add_argument("-c", "--customer", default=None, help="Customer/owner name or QBO ID")
    gl_p.add_argument(
        "-a", "--account", default=None, help="Top-level account ID or name (auto-discovers sub-accounts)"
    )
    gl_p.add_argument(
        "-b",
        "--begin",
        "--start",
        default=None,
        dest="start",
        help="Start date YYYY-MM-DD or DD.MM.YYYY (default: first transaction)",
    )
    gl_p.add_argument("-e", "--end", default=None, help="End date YYYY-MM-DD or DD.MM.YYYY (default: today)")
    gl_p.add_argument("--method", default="Cash", choices=["Cash", "Accrual"], help="Accounting method (default: Cash)")
    gl_p.add_argument("--currency", default="", help="Currency prefix for display (e.g. THB, USD, €)")
    gl_p.add_argument(
        "--list-accounts", action="store_true", help="List account hierarchy (or all top-level if -a omitted)"
    )
    gl_p.add_argument(
        "-o",
        "--output",
        "--format",
        dest="output",
        default=None,
        choices=GL_OUTPUT_FORMATS,
        help="Output format: text (default), json, txns (flat transaction list), expanded (tree + transactions)",
    )
    gl_p.add_argument("--no-sub", action="store_true", help="Don't break down into sub-accounts (roll up into parent)")
    gl_p.add_argument(
        "-g", "--by-customer", action="store_true", help="Group by customer (shows per-customer subtotals)"
    )
    gl_p.add_argument(
        "-s",
        "--sort",
        default="alpha",
        choices=["alpha", "amount"],
        help="Sort order for --by-customer: alpha (default) or amount",
    )

    return parser, auth_p


def _resolve_profile(args) -> str:
    """Resolve profile name from CLI flags, env var, or default."""
    if args.profile:
        return args.profile
    if args.sandbox:
        return "dev"
    return os.environ.get("QBO_PROFILE", "prod")


def _build_runtime(args) -> tuple[Config, TokenManager]:
    """Create runtime config and token manager for parsed args."""
    profile = _resolve_profile(args)
    config = Config(profile=profile)
    if args.sandbox and not args.profile:
        config.sandbox = True
    return config, TokenManager(config)


def _dispatch_command(args, auth_parser: argparse.ArgumentParser, config: Config, token_mgr: TokenManager) -> None:
    """Dispatch parsed CLI args to the appropriate handler."""
    if args.command == "auth":
        if not args.auth_command:
            auth_parser.print_help()
            sys.exit(1)

        auth_dispatch = {
            "init": cmd_auth_init,
            "status": cmd_auth_status,
            "refresh": cmd_auth_refresh,
            "setup": cmd_auth_setup,
        }
        auth_dispatch[args.auth_command](args, config, token_mgr)
        return

    dispatch = {
        "query": cmd_query,
        "search": cmd_search,
        "get": cmd_get,
        "create": cmd_create,
        "update": cmd_update,
        "delete": cmd_delete,
        "void": cmd_void,
        "report": cmd_report,
        "raw": cmd_raw,
        "gl-report": cmd_gl_report,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        die(f"Unknown command '{args.command}'")

    config.validate()
    handler(args, config, token_mgr)


def main() -> None:
    parser, auth_parser = _build_parser()

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config, token_mgr = _build_runtime(args)
    _dispatch_command(args, auth_parser, config, token_mgr)


if __name__ == "__main__":
    main()
