"""QBO OAuth token management and auth CLI commands."""

from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from qbo_cli.config import Config
from qbo_cli.constants import (
    AUTH_URL,
    CONFIG_PATH,
    DEFAULT_REDIRECT,
    QBO_DIR,
    REFRESH_EXPIRY_WARN_DAYS,
    REFRESH_MARGIN_SEC,
    SCOPE,
    TOKEN_URL,
)
from qbo_cli.errors import die, err_print
from qbo_cli.output import output


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
        if _is_token_fresh(tokens):
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
                if _is_token_fresh(current):
                    return current["access_token"]

                new_tokens = self._do_refresh(current)
                self.save(new_tokens)
                return new_tokens["access_token"]
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _do_refresh(self, tokens: dict) -> dict:
        """Call Intuit token endpoint to refresh."""
        resp = self._post_token_endpoint(
            {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
            failure_label="Token refresh",
        )
        self._raise_on_refresh_error(resp)
        return _build_token_envelope(
            resp.json(),
            realm_id=tokens.get("realm_id", self.config.realm_id),
            created_at=tokens.get("created_at", time.time()),
        )

    def exchange_code(self, auth_code: str, realm_id: str) -> dict:
        """Exchange authorization code for tokens."""
        resp = self._post_token_endpoint(
            {
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": self.config.redirect_uri,
            },
            failure_label="Code exchange",
        )
        if not resp.ok:
            die(f"Code exchange failed (HTTP {resp.status_code}): {resp.text[:500]}")

        tokens = _build_token_envelope(resp.json(), realm_id=realm_id, created_at=time.time())
        self.save(tokens)
        return tokens

    def _post_token_endpoint(self, payload: dict, *, failure_label: str) -> requests.Response:
        """POST to Intuit token endpoint with shared error handling."""
        try:
            return requests.post(
                TOKEN_URL,
                data=payload,
                auth=(self.config.client_id, self.config.client_secret),
                timeout=30,
            )
        except requests.ConnectionError:
            die(f"Network error during {failure_label.lower()}. Check your connection.")
        except requests.Timeout:
            die(f"Timeout during {failure_label.lower()}. Intuit OAuth may be down.")
        return None  # unreachable — die() exits

    @staticmethod
    def _raise_on_refresh_error(resp: requests.Response) -> None:
        """Translate refresh-endpoint failures into actionable die() calls."""
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


def _is_token_fresh(tokens: dict) -> bool:
    """Return True when the access token is still within the refresh margin."""
    expires_at = tokens.get("expires_at", 0)
    return time.time() < expires_at - REFRESH_MARGIN_SEC


def _build_token_envelope(data: dict, *, realm_id: str, created_at: float) -> dict:
    """Build the on-disk token envelope from an Intuit token response."""
    now = time.time()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": now + data["expires_in"],
        "refresh_expires_at": now + data.get("x_refresh_token_expires_in", 8640000),
        "realm_id": realm_id,
        "token_type": data.get("token_type", "bearer"),
        "created_at": created_at,
        "refreshed_at": now,
    }


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
    output(info, getattr(args, "output", None) or args.format)


def cmd_auth_refresh(args, config, token_mgr):
    config.validate()
    token_mgr.load()
    token_mgr._locked_refresh(token_mgr._tokens)
    err_print("✓ Token refreshed successfully")


def cmd_auth_setup(args, config, token_mgr):
    """Interactive config setup — creates/updates ~/.qbo/config.json with profiled format."""
    profile = config.profile
    _print_setup_header(profile)

    all_profiles = _load_all_profiles_for_setup()
    existing = all_profiles.get(profile, {})

    creds = _collect_setup_credentials(existing)
    if not creds[0] or not creds[1]:
        die("Client ID and Client Secret are required.")

    all_profiles[profile] = _build_profile_section(existing, profile, creds)
    _write_profiles_atomic(all_profiles)
    _print_setup_next_steps(profile)


def _print_setup_header(profile: str) -> None:
    print(f"QuickBooks Online CLI — Setup (profile: {profile})")
    print("=" * 40)
    print()
    print("You need a QuickBooks app from https://developer.intuit.com")
    print("Go to: Dashboard → Create an app → Get your Client ID & Secret")
    print()


def _load_all_profiles_for_setup() -> dict:
    """Load full config file (all profiles), migrating legacy flat shape under 'prod'."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    if "client_id" in raw:
        err_print("Migrating from legacy flat config to profiled format.")
        return {"prod": raw}
    return raw


def _prompt_with_hint(label: str, current: str, *, secret: bool = False) -> str:
    """Prompt for ``label``, showing ``current`` as the default hint (masked when secret)."""
    if current and secret:
        display = current[:4] + "..." + current[-4:] if len(current) > 12 else "***"
        hint = f" [{display}]"
    elif current:
        hint = f" [{current}]"
    else:
        hint = ""
    val = input(f"{label}{hint}: ").strip()
    return val if val else current


def _collect_setup_credentials(existing: dict) -> tuple:
    """Prompt for client_id, client_secret, redirect_uri and return as a tuple."""
    client_id = _prompt_with_hint("Client ID", existing.get("client_id", ""))
    client_secret = _prompt_with_hint("Client Secret", existing.get("client_secret", ""), secret=True)
    redirect_uri = _prompt_with_hint("Redirect URI", existing.get("redirect_uri", DEFAULT_REDIRECT))
    return client_id, client_secret, redirect_uri


def _build_profile_section(existing: dict, profile: str, creds: tuple) -> dict:
    """Assemble a profile section, preserving realm_id and sandbox where present."""
    client_id, client_secret, redirect_uri = creds
    section: dict = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    if existing.get("realm_id"):
        section["realm_id"] = existing["realm_id"]
    if existing.get("sandbox"):
        section["sandbox"] = existing["sandbox"]
    elif profile == "dev":
        section["sandbox"] = True
    return section


def _write_profiles_atomic(all_profiles: dict) -> None:
    """Write the full config file atomically with restrictive permissions."""
    QBO_DIR.mkdir(parents=True, exist_ok=True)
    QBO_DIR.chmod(0o700)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_profiles, indent=2) + "\n")
    tmp.chmod(0o600)
    tmp.rename(CONFIG_PATH)


def _print_setup_next_steps(profile: str) -> None:
    profile_flag = f"--profile {profile} " if profile != "prod" else ""
    print()
    print(f"✓ Config saved to {CONFIG_PATH} (profile: {profile})")
    print()
    print("Next step — authorize with QuickBooks:")
    print(f"  qbo {profile_flag}auth init")
    print()
    print("On a headless server (no browser):")
    print(f"  qbo {profile_flag}auth init --manual")
