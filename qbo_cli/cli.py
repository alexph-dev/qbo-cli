#!/usr/bin/env python3
"""qbo-cli — Command-line interface for QuickBooks Online API.

A single-file CLI for interacting with the QuickBooks Online (QBO) API.
Supports OAuth 2.0 authentication, querying entities with auto-pagination,
CRUD operations, financial reports, and raw API access.

Homepage: https://github.com/alexph-dev/qbo-cli
License: MIT
"""

import argparse
import fcntl
import json
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

# ─── Constants ───────────────────────────────────────────────────────────────

QBO_DIR = Path.home() / ".qbo"
CONFIG_PATH = QBO_DIR / "config.json"
TOKENS_PATH = QBO_DIR / "tokens.json"
AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
PROD_BASE = "https://quickbooks.api.intuit.com/v3/company"
SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"
SCOPE = "com.intuit.quickbooks.accounting"
DEFAULT_REDIRECT = "http://localhost:8844/callback"
REFRESH_MARGIN_SEC = 300   # 5 minutes
MAX_RESULTS = 1000         # QBO max per page
DEFAULT_MAX_PAGES = 100    # safety cap
MINOR_VERSION = 75         # QBO API minor version
REFRESH_EXPIRY_WARN_DAYS = 14  # warn when refresh token < this many days left


# ─── Helpers ─────────────────────────────────────────────────────────────────

def die(msg: str, code: int = 1):
    """Print to stderr and exit."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


def err_print(msg: str):
    print(msg, file=sys.stderr)


def output(data, fmt: str = "json"):
    """Write result to stdout."""
    if fmt == "tsv":
        output_tsv(data)
    else:
        json.dump(data, sys.stdout, indent=2, default=str)
        print()


def output_tsv(data):
    """Flatten list-of-dicts to TSV."""
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                data = v
                break
        else:
            data = [data]
    if not data:
        return
    if isinstance(data, list) and data and isinstance(data[0], dict):
        keys = list(data[0].keys())
        print("\t".join(keys))
        for row in data:
            print("\t".join(str(row.get(k, "")) for k in keys))
    else:
        json.dump(data, sys.stdout, indent=2, default=str)
        print()


# ─── Config ──────────────────────────────────────────────────────────────────

class Config:
    """Load config from env vars → config file → defaults."""

    def __init__(self):
        self.client_id: str = ""
        self.client_secret: str = ""
        self.redirect_uri: str = DEFAULT_REDIRECT
        self.realm_id: str = ""
        self.sandbox: bool = False
        self._load()

    def _load(self):
        file_cfg = {}
        if CONFIG_PATH.exists():
            try:
                file_cfg = json.loads(CONFIG_PATH.read_text())
            except json.JSONDecodeError:
                err_print("Warning: ~/.qbo/config.json is not valid JSON, ignoring.")

        self.client_id = os.environ.get("QBO_CLIENT_ID", file_cfg.get("client_id", ""))
        self.client_secret = os.environ.get("QBO_CLIENT_SECRET", file_cfg.get("client_secret", ""))
        self.redirect_uri = os.environ.get("QBO_REDIRECT_URI", file_cfg.get("redirect_uri", DEFAULT_REDIRECT))
        self.realm_id = os.environ.get("QBO_REALM_ID", file_cfg.get("realm_id", ""))
        self.sandbox = os.environ.get("QBO_SANDBOX", file_cfg.get("sandbox", False))
        if isinstance(self.sandbox, str):
            self.sandbox = self.sandbox.lower() in ("1", "true", "yes")

    def validate(self, need_tokens=True):
        """Raise if missing required config."""
        if not self.client_id or not self.client_secret:
            die(
                "Missing QBO credentials. Run setup first:\n"
                "  qbo auth setup\n\n"
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
        if not TOKENS_PATH.exists():
            die("No tokens found. Run: qbo auth init")
        try:
            self._tokens = json.loads(TOKENS_PATH.read_text())
        except json.JSONDecodeError:
            die("Token file corrupted. Delete ~/.qbo/tokens.json and re-run: qbo auth init")
        return self._tokens

    def save(self, tokens: dict):
        """Atomic write: temp file → rename. Permissions set before rename."""
        QBO_DIR.mkdir(parents=True, exist_ok=True)
        tmp = TOKENS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(tokens, indent=2))
        tmp.chmod(0o600)  # set permissions BEFORE rename to avoid exposure window
        tmp.rename(TOKENS_PATH)
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
        lock_path = TOKENS_PATH.with_suffix(".lock")
        QBO_DIR.mkdir(parents=True, exist_ok=True)

        with open(lock_path, "w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                # Re-read — another process may have refreshed
                tokens = self.load()
                if time.time() < tokens["expires_at"] - REFRESH_MARGIN_SEC:
                    return tokens["access_token"]

                new_tokens = self._do_refresh(tokens)
                self.save(new_tokens)
                return new_tokens["access_token"]
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _do_refresh(self, tokens: dict) -> dict:
        """Call Intuit token endpoint to refresh."""
        try:
            resp = requests.post(TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
            }, auth=(self.config.client_id, self.config.client_secret), timeout=30)
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
            resp = requests.post(TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": self.config.redirect_uri,
            }, auth=(self.config.client_id, self.config.client_secret), timeout=30)
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

    def request(self, method: str, path: str, params: dict = None,
                json_body: dict = None, raw_response: bool = False):
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
                    method, url,
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
                    error_detail = "; ".join(
                        f"{e.get('Message', '')} — {e.get('Detail', '')}" for e in errors
                    )
            except (ValueError, AttributeError):
                pass
            err_print(f"API error {resp.status_code}: {error_detail}")
            sys.exit(1)

        return resp.json()

    def query(self, sql: str, max_pages: int = DEFAULT_MAX_PAGES) -> list:
        """Run QBO query with auto-pagination."""
        all_results = []
        start = 1

        for page in range(max_pages):
            paginated_sql = f"{sql} STARTPOSITION {start} MAXRESULTS {MAX_RESULTS}"
            data = self.request("GET", "query", params={"query": paginated_sql})

            qr = data.get("QueryResponse", {})
            entities = []
            for key, val in qr.items():
                if isinstance(val, list):
                    entities = val
                    break

            all_results.extend(entities)

            if len(entities) < MAX_RESULTS:
                break
            start += MAX_RESULTS

        return all_results

    def get(self, entity: str, entity_id: str) -> dict:
        return self.request("GET", f"{entity}/{entity_id}")

    def create(self, entity: str, body: dict) -> dict:
        return self.request("POST", entity, json_body=body)

    def update(self, entity: str, body: dict) -> dict:
        return self.request("POST", entity, json_body=body)

    def delete(self, entity: str, entity_id: str) -> dict:
        current = self.get(entity, entity_id)
        entity_data = current.get(entity, current)
        return self.request("POST", entity,
                            params={"operation": "delete"},
                            json_body=entity_data)

    def report(self, report_type: str, params: dict = None) -> dict:
        return self.request("GET", f"reports/{report_type}", params=params)

    def raw(self, method: str, path: str, body: dict = None) -> dict:
        return self.request(method.upper(), path, json_body=body)


# ─── GL Report Engine ────────────────────────────────────────────────────────

class GLSection:
    """Parsed GL account section with amounts and sub-sections."""

    def __init__(self, name: str, acct_id: str = ""):
        self.name = name
        self.id = acct_id
        self.direct_amount = 0.0
        self.direct_count = 0
        self.children: list["GLSection"] = []

    @property
    def total_amount(self) -> float:
        return self.direct_amount + sum(c.total_amount for c in self.children)

    @property
    def total_count(self) -> int:
        return self.direct_count + sum(c.total_count for c in self.children)


def _parse_gl_rows(rows_obj: dict) -> list[GLSection]:
    """Parse GL Rows object into list of GLSection."""
    sections = []
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
                        cols = inner_row.get("ColData", [])
                        if cols and cols[0].get("value", "") == "Beginning Balance":
                            continue
                        amt_str = cols[6].get("value", "") if len(cols) > 6 else ""
                        if amt_str:
                            try:
                                placeholder.direct_amount += float(amt_str)
                                placeholder.direct_count += 1
                            except ValueError:
                                pass
            sections.append(placeholder)
            continue

        section = GLSection(name, acct_id)
        inner_rows = row.get("Rows", {})

        if inner_rows and "Row" in inner_rows:
            for inner_row in inner_rows["Row"]:
                if inner_row.get("type") == "Data":
                    cols = inner_row.get("ColData", [])
                    if cols and cols[0].get("value", "") == "Beginning Balance":
                        continue
                    amt_str = cols[6].get("value", "") if len(cols) > 6 else ""
                    if amt_str:
                        try:
                            section.direct_amount += float(amt_str)
                            section.direct_count += 1
                        except ValueError:
                            pass

        section.children = _parse_gl_rows(inner_rows)
        absorbed = [c for c in section.children if c.name == "__direct__"]
        for a in absorbed:
            section.direct_amount += a.direct_amount
            section.direct_count += a.direct_count
        section.children = [c for c in section.children if c.name != "__direct__"]

        sections.append(section)

    return sections


def _find_gl_section(sections: list[GLSection], name: str) -> GLSection | None:
    """Find a GL section by name (recursive, suffix-match for numbered accounts)."""
    for s in sections:
        if s.name == name or s.name.endswith(f" {name}"):
            return s
        found = _find_gl_section(s.children, name)
        if found:
            return found
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
        accts = client.query(
            f"SELECT Id, Name, FullyQualifiedName FROM Account WHERE Id = '{account_ref}'"
        )
        parent_name = (accts[0].get("FullyQualifiedName", accts[0].get("Name", f"Account {account_ref}"))
                       if accts else f"Account {account_ref}")
    else:
        accts = client.query(
            f"SELECT Id, Name, FullyQualifiedName FROM Account WHERE Name LIKE '%{account_ref}%'"
        )
        if not accts:
            die(f"No account found matching '{account_ref}'")
        match = next((a for a in accts if a["Name"].lower() == account_ref.lower()), accts[0])
        parent_id = match["Id"]
        parent_name = match.get("FullyQualifiedName", match["Name"])

    all_accts = client.query(
        "SELECT Id, Name, FullyQualifiedName, SubAccount, ParentRef FROM Account"
    )

    def build_children(pid: str) -> list[dict]:
        kids = []
        for a in all_accts:
            pr = a.get("ParentRef", {})
            if isinstance(pr, dict) and pr.get("value") == pid:
                kids.append({
                    "name": a["Name"],
                    "id": a["Id"],
                    "children": build_children(a["Id"]),
                })
        kids.sort(key=lambda x: x["name"])
        return kids

    return {
        "name": parent_name.split(":")[-1].strip(),
        "id": parent_id,
        "children": build_children(parent_id),
    }


def _list_all_accounts(client: "QBOClient"):
    """Print all top-level accounts grouped by type."""
    all_accts = client.query(
        "SELECT Id, Name, FullyQualifiedName, AccountType, SubAccount, ParentRef FROM Account"
    )

    def count_descendants(pid: str) -> int:
        total = 0
        for a in all_accts:
            pr = a.get("ParentRef", {})
            if isinstance(pr, dict) and pr.get("value") == pid:
                total += 1 + count_descendants(a["Id"])
        return total

    top = [a for a in all_accts if not a.get("SubAccount", False)]
    top.sort(key=lambda a: (a.get("AccountType", ""), a.get("Name", "")))

    current_type = None
    for a in top:
        atype = a.get("AccountType", "Other")
        if atype != current_type:
            if current_type is not None:
                print()
            print(f"── {atype} ──")
            current_type = atype
        desc = count_descendants(a["Id"])
        sub_str = f"  ({desc} sub-accounts)" if desc else ""
        print(f"  {a['Id']:>15}  {a['Name']}{sub_str}")

    print(f"\n{len(top)} top-level accounts, {len(all_accts)} total")


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
    customers = client.query(
        f"SELECT Id, DisplayName, FullyQualifiedName FROM Customer WHERE DisplayName = '{name}'"
    )
    if not customers:
        customers = client.query(
            f"SELECT Id, DisplayName, FullyQualifiedName FROM Customer WHERE DisplayName LIKE '%{name}%'"
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


REPORT_WIDTH = 72


def _format_amount(amount: float, currency: str = "") -> str:
    prefix = currency or ""
    if amount < 0:
        return f"-{prefix}{abs(amount):,.2f}"
    return f"{prefix}{amount:,.2f}"


def _format_date_range(start: str, end: str) -> str:
    from datetime import datetime as dt
    s = dt.strptime(start, "%Y-%m-%d")
    e = dt.strptime(end, "%Y-%m-%d")
    if s.month == e.month and s.year == e.year:
        return f"{s.strftime('%B')}, {s.year}"
    elif s.year == e.year:
        return f"{s.strftime('%B')}-{e.strftime('%B')}, {s.year}"
    return f"{s.strftime('%B %Y')}-{e.strftime('%B %Y')}"


def _pad_line(label: str, amt_str: str, prefix: str = "") -> str:
    total_len = len(prefix) + len(label) + len(amt_str)
    pad = max(1, REPORT_WIDTH - total_len)
    return f"{prefix}{label}{' ' * pad}{amt_str}"


def _compute_subtotal(gl_sections: list[GLSection], node: dict) -> tuple[float, int]:
    """Compute total for a tree node (own + children, recursively)."""
    if not node["children"]:
        section = _find_gl_section(gl_sections, node["name"])
        if section:
            return section.total_amount, section.total_count
        return 0.0, 0

    section = _find_gl_section(gl_sections, node["name"])
    total_amt = section.direct_amount if section else 0.0
    total_cnt = section.direct_count if section else 0
    for child in node["children"]:
        c_amt, c_cnt = _compute_subtotal(gl_sections, child)
        total_amt += c_amt
        total_cnt += c_cnt
    return total_amt, total_cnt


def _build_report_lines(gl_sections: list[GLSection], node: dict,
                        currency: str, indent: int = 0, lines: list | None = None) -> list[str]:
    if lines is None:
        lines = []

    prefix = "  " * indent
    subtotal_amt, subtotal_cnt = _compute_subtotal(gl_sections, node)

    if not node["children"]:
        section = _find_gl_section(gl_sections, node["name"])
        amt = section.total_amount if section else 0.0
        cnt = section.total_count if section else 0
        if cnt == 0 and amt == 0.0:
            return lines
        lines.append(_pad_line(f"{node['name']} ({cnt})", _format_amount(amt, currency), prefix))
    else:
        if subtotal_cnt == 0 and subtotal_amt == 0.0:
            return lines

        section = _find_gl_section(gl_sections, node["name"])
        own_cnt = section.direct_count if section else 0
        own_amt = section.direct_amount if section else 0.0
        if own_cnt > 0:
            lines.append(_pad_line(f"{node['name']} ({own_cnt})", _format_amount(own_amt, currency), prefix))
        else:
            lines.append(f"{prefix}{node['name']}")

        for child in node["children"]:
            _build_report_lines(gl_sections, child, currency, indent + 1, lines)

        lines.append(_pad_line(f"Total for {node['name']}", _format_amount(subtotal_amt, currency), prefix))

    return lines


def cmd_gl_report(args, config, token_mgr):
    """Generate a hierarchical General Ledger report."""
    from datetime import datetime as dt

    client = QBOClient(config, token_mgr)

    # --list-accounts mode
    if args.list_accounts:
        if args.account:
            tree = _discover_account_tree(client, args.account)
            _print_account_tree(tree)
        else:
            _list_all_accounts(client)
        return

    # Resolve customer (optional)
    cust_id, cust_name = None, None
    if args.customer:
        cust_id, cust_name = _resolve_customer(client, args.customer)

    # Resolve dates
    end_date = args.end or dt.now().strftime("%Y-%m-%d")
    start_date = args.start or "2000-01-01"
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

    # Auto-detect start date
    display_start = start_date
    if auto_start:
        actual_first, _ = _extract_dates_from_gl(gl_data)
        if actual_first:
            display_start = actual_first

    # Output
    if args.format == "json" and not args.text:
        # JSON output: structured data
        total_amt, total_cnt = _compute_subtotal(gl_sections, account_tree)

        def tree_to_dict(node):
            section = _find_gl_section(gl_sections, node["name"])
            result = {"name": node["name"], "id": node["id"]}
            if not node["children"]:
                result["amount"] = section.total_amount if section else 0.0
                result["count"] = section.total_count if section else 0
            else:
                result["direct_amount"] = section.direct_amount if section else 0.0
                result["direct_count"] = section.direct_count if section else 0
                amt, cnt = _compute_subtotal(gl_sections, node)
                result["total_amount"] = amt
                result["total_count"] = cnt
                result["children"] = [tree_to_dict(c) for c in node["children"]]
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

        output(report_data)
    else:
        # Text report
        date_range = _format_date_range(display_start, end_date)
        total_amt, _ = _compute_subtotal(gl_sections, account_tree)
        currency = args.currency

        title = f"General Ledger Report - {cust_name}" if cust_name else "General Ledger Report"
        lines = [
            title,
            date_range,
            "",
        ]
        _build_report_lines(gl_sections, account_tree, currency, indent=0, lines=lines)
        lines.append("")
        lines.append(_pad_line("TOTAL", _format_amount(total_amt, currency)))
        print("\n".join(lines))


# ─── Auth Commands ───────────────────────────────────────────────────────────

def cmd_auth_init(args, config, token_mgr):
    """Interactive OAuth authorization flow."""
    config.validate(need_tokens=False)

    auth_params = urlencode({
        "client_id": config.client_id,
        "scope": SCOPE,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "state": os.urandom(16).hex(),
    })
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
    else:
        code, realm_id = _run_callback_server(auth_url, config, args.port)

    tokens = token_mgr.exchange_code(code, realm_id)
    err_print(f"✓ Authorized. Realm: {realm_id}")
    err_print(f"  Access token expires: {time.ctime(tokens['expires_at'])}")
    err_print(f"  Refresh token expires: {time.ctime(tokens['refresh_expires_at'])}")


def _run_callback_server(auth_url: str, config: Config, port: int) -> tuple:
    """Start temp HTTP server, print auth URL, wait for callback."""
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
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
    tokens = token_mgr.load()
    now = time.time()
    access_exp = tokens.get("expires_at", 0)
    refresh_exp = tokens.get("refresh_expires_at", 0)

    info = {
        "realm_id": tokens.get("realm_id"),
        "access_token_valid": access_exp > now,
        "access_token_expires": time.ctime(access_exp),
        "access_token_remaining_min": max(0, round((access_exp - now) / 60, 1)),
        "refresh_token_expires": time.ctime(refresh_exp),
        "refresh_token_remaining_days": max(0, round((refresh_exp - now) / 86400, 1)),
        "last_refreshed": time.ctime(tokens.get("refreshed_at", 0)),
    }
    output(info, args.format)


def cmd_auth_refresh(args, config, token_mgr):
    config.validate(need_tokens=False)
    token_mgr.load()
    token_mgr._locked_refresh(token_mgr._tokens)
    err_print("✓ Token refreshed successfully")


def cmd_auth_setup(args, config, token_mgr):
    """Interactive config setup — creates ~/.qbo/config.json."""
    print("QuickBooks Online CLI — Setup")
    print("=" * 40)
    print()
    print("You need a QuickBooks app from https://developer.intuit.com")
    print("Go to: Dashboard → Create an app → Get your Client ID & Secret")
    print()

    # Load existing values as defaults
    existing = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text())
        except json.JSONDecodeError:
            pass

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

    cfg = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }

    # Preserve existing realm_id / sandbox if present
    if existing.get("realm_id"):
        cfg["realm_id"] = existing["realm_id"]
    if existing.get("sandbox"):
        cfg["sandbox"] = existing["sandbox"]

    QBO_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")
    os.chmod(CONFIG_PATH, 0o600)

    print()
    print(f"✓ Config saved to {CONFIG_PATH}")
    print()
    print("Next step — authorize with QuickBooks:")
    print("  qbo auth init")
    print()
    print("On a headless server (no browser):")
    print("  qbo auth init --manual")


# ─── Entity Commands ─────────────────────────────────────────────────────────

def cmd_query(args, config, token_mgr):
    client = QBOClient(config, token_mgr)
    results = client.query(args.sql, max_pages=args.max_pages)
    output(results, args.format)


def cmd_get(args, config, token_mgr):
    client = QBOClient(config, token_mgr)
    result = client.get(args.entity, args.id)
    output(result, args.format)


def cmd_create(args, config, token_mgr):
    if sys.stdin.isatty():
        die("Pipe JSON body via stdin. Example: echo '{...}' | qbo create Invoice")
    try:
        body = json.load(sys.stdin)
    except json.JSONDecodeError:
        die("Invalid JSON on stdin.")
    client = QBOClient(config, token_mgr)
    result = client.create(args.entity, body)
    output(result, args.format)


def cmd_update(args, config, token_mgr):
    if sys.stdin.isatty():
        die("Pipe JSON body via stdin. Example: echo '{...}' | qbo update Customer")
    try:
        body = json.load(sys.stdin)
    except json.JSONDecodeError:
        die("Invalid JSON on stdin.")
    client = QBOClient(config, token_mgr)
    result = client.update(args.entity, body)
    output(result, args.format)


def cmd_delete(args, config, token_mgr):
    client = QBOClient(config, token_mgr)
    result = client.delete(args.entity, args.id)
    output(result, args.format)


def cmd_report(args, config, token_mgr):
    client = QBOClient(config, token_mgr)
    params = {}
    if args.start_date:
        params["start_date"] = args.start_date
    if args.end_date:
        params["end_date"] = args.end_date
    if args.date_macro:
        params["date_macro"] = args.date_macro
    if args.params:
        for p in args.params:
            if "=" not in p:
                die(f"Invalid param format '{p}'. Use key=value.")
            k, v = p.split("=", 1)
            params[k] = v
    result = client.report(args.report_type, params or None)
    output(result, args.format)


def cmd_raw(args, config, token_mgr):
    client = QBOClient(config, token_mgr)
    body = None
    if args.method.upper() in ("POST", "PUT") and not sys.stdin.isatty():
        try:
            body = json.load(sys.stdin)
        except json.JSONDecodeError:
            die("Invalid JSON on stdin.")
    result = client.raw(args.method, args.path, body)
    output(result, args.format)


# ─── CLI Parser ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="qbo",
        description="QuickBooks Online CLI — query, create, update, delete entities and run reports.",
    )
    parser.add_argument("--format", "-f", choices=["json", "tsv"], default="json",
                        help="Output format (default: json)")
    parser.add_argument("--sandbox", action="store_true",
                        help="Use sandbox API endpoint")

    subs = parser.add_subparsers(dest="command")

    # ── auth ──
    auth_p = subs.add_parser("auth", help="Authentication commands")
    auth_subs = auth_p.add_subparsers(dest="auth_command")

    init_p = auth_subs.add_parser("init", help="Start OAuth authorization flow")
    init_p.add_argument("--manual", action="store_true",
                        help="Manual mode: paste redirect URL instead of local callback server")
    init_p.add_argument("--port", type=int, default=8844,
                        help="Callback server port (default: 8844)")

    auth_subs.add_parser("status", help="Show token status")
    auth_subs.add_parser("refresh", help="Force token refresh")
    auth_subs.add_parser("setup", help="Interactive config setup (creates ~/.qbo/config.json)")

    # ── query ──
    query_p = subs.add_parser("query", help="Run a QBO query (SQL-like)")
    query_p.add_argument("sql", help='QBO query, e.g. "SELECT * FROM Customer"')
    query_p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                         help=f"Max pagination pages (default: {DEFAULT_MAX_PAGES})")

    # ── get ──
    get_p = subs.add_parser("get", help="Get a single entity by ID")
    get_p.add_argument("entity", help="Entity type (Invoice, Customer, etc.)")
    get_p.add_argument("id", help="Entity ID")

    # ── create ──
    create_p = subs.add_parser("create", help="Create an entity (JSON on stdin)")
    create_p.add_argument("entity", help="Entity type")

    # ── update ──
    update_p = subs.add_parser("update", help="Update an entity (JSON on stdin)")
    update_p.add_argument("entity", help="Entity type")

    # ── delete ──
    delete_p = subs.add_parser("delete", help="Delete an entity by ID")
    delete_p.add_argument("entity", help="Entity type")
    delete_p.add_argument("id", help="Entity ID")

    # ── report ──
    report_p = subs.add_parser("report", help="Run a QBO report")
    report_p.add_argument("report_type", help="Report type (ProfitAndLoss, BalanceSheet, etc.)")
    report_p.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    report_p.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    report_p.add_argument("--date-macro", help='Date macro (e.g. "Last Month", "This Year")')
    report_p.add_argument("params", nargs="*", help="Extra params as key=value")

    # ── raw ──
    raw_p = subs.add_parser("raw", help="Make a raw API request")
    raw_p.add_argument("method", help="HTTP method (GET, POST, PUT, DELETE)")
    raw_p.add_argument("path", help="API path after /v3/company/{realm}/")

    # ── gl-report ──
    gl_p = subs.add_parser("gl-report", help="Hierarchical General Ledger report by account & customer",
                           formatter_class=argparse.RawDescriptionHelpFormatter,
                           epilog="""examples:
  %(prog)s -c "John Smith" -a 125                    # report for account 125
  %(prog)s -c "John Smith" -a "Revenue" --start 2025-01-01
  %(prog)s -c "John Smith" -a 125 --currency USD     # custom currency prefix
  %(prog)s --list-accounts                            # list all top-level accounts
  %(prog)s -a 125 --list-accounts                     # show sub-account tree""")
    gl_p.add_argument("-c", "--customer", default=None,
                      help="Customer/owner name or QBO ID")
    gl_p.add_argument("-a", "--account", default=None,
                      help="Top-level account ID or name (auto-discovers sub-accounts)")
    gl_p.add_argument("--start", default=None,
                      help="Start date YYYY-MM-DD (default: first transaction)")
    gl_p.add_argument("--end", default=None,
                      help="End date YYYY-MM-DD (default: today)")
    gl_p.add_argument("--method", default="Cash", choices=["Cash", "Accrual"],
                      help="Accounting method (default: Cash)")
    gl_p.add_argument("--currency", default="",
                      help="Currency prefix for display (e.g. THB, USD, €)")
    gl_p.add_argument("--list-accounts", action="store_true",
                      help="List account hierarchy (or all top-level if -a omitted)")
    gl_p.add_argument("--text", action="store_true",
                      help="Human-readable text output (default is JSON)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = Config()
    if args.sandbox:
        config.sandbox = True
    token_mgr = TokenManager(config)

    # ── Dispatch ──
    if args.command == "auth":
        if not args.auth_command:
            auth_p.print_help()
            sys.exit(1)
        dispatch = {
            "init": cmd_auth_init,
            "status": cmd_auth_status,
            "refresh": cmd_auth_refresh,
            "setup": cmd_auth_setup,
        }
        dispatch[args.auth_command](args, config, token_mgr)
    elif args.command == "query":
        config.validate()
        cmd_query(args, config, token_mgr)
    elif args.command == "get":
        config.validate()
        cmd_get(args, config, token_mgr)
    elif args.command == "create":
        config.validate()
        cmd_create(args, config, token_mgr)
    elif args.command == "update":
        config.validate()
        cmd_update(args, config, token_mgr)
    elif args.command == "delete":
        config.validate()
        cmd_delete(args, config, token_mgr)
    elif args.command == "report":
        config.validate()
        cmd_report(args, config, token_mgr)
    elif args.command == "raw":
        config.validate()
        cmd_raw(args, config, token_mgr)
    elif args.command == "gl-report":
        config.validate()
        cmd_gl_report(args, config, token_mgr)


if __name__ == "__main__":
    main()
