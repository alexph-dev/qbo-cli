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
