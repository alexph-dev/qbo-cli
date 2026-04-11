"""Shared constants: URLs, paths, API parameters, output formats."""

from __future__ import annotations

import re
from pathlib import Path

QBO_DIR = Path.home() / ".qbo"
CONFIG_PATH = QBO_DIR / "config.json"
AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
PROD_BASE = "https://quickbooks.api.intuit.com/v3/company"
SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"
SCOPE = "com.intuit.quickbooks.accounting"
DEFAULT_REDIRECT = "http://localhost:8844/callback"
REFRESH_MARGIN_SEC = 300  # 5 minutes
MAX_RESULTS = 1000  # QBO max per page
DEFAULT_MAX_PAGES = 100  # safety cap
MINOR_VERSION = 75  # QBO API minor version
REFRESH_EXPIRY_WARN_DAYS = 14  # warn when refresh token < this many days left
OUTPUT_FORMATS = ("text", "json", "tsv")
PROFILE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
GL_OUTPUT_FORMATS = ("text", "json", "txns", "expanded")
FMT_HELP = "Output format: text (default), json, tsv"
REPORT_WIDTH = 72
