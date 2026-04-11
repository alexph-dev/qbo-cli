"""QBO CLI configuration loader with profile support."""

from __future__ import annotations

import json
import os
from pathlib import Path

from qbo_cli.constants import CONFIG_PATH, DEFAULT_REDIRECT, PROFILE_RE, QBO_DIR
from qbo_cli.errors import die, err_print


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
