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
                "Missing QBO_CLIENT_ID / QBO_CLIENT_SECRET.\n"
                "Set env vars or create ~/.qbo/config.json with client_id and client_secret."
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


if __name__ == "__main__":
    main()
