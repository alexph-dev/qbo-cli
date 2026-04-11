"""Shared CLI option and parameter helpers.

Pure helpers used by command handlers and the GL-report engine. Breaks the
otherwise-circular dependency between commands.py and gl_report.py by hosting
format resolution, date parsing, stdin JSON reading, client construction, and
report parameter building in one leaf module.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime

from qbo_cli.auth import TokenManager
from qbo_cli.client import QBOClient
from qbo_cli.config import Config
from qbo_cli.errors import die
from qbo_cli.output import output


def _resolve_fmt(args) -> str:
    """Resolve output format: subcommand -o overrides global -f."""
    return getattr(args, "output", None) or args.format


def _make_client(config: Config, token_mgr: TokenManager) -> QBOClient:
    """Build a client for command handlers."""
    return QBOClient(config, token_mgr)


def _parse_date(value: str) -> str:
    """Parse flexible date input → YYYY-MM-DD string.

    Accepts: YYYY-MM-DD, DD.MM.YYYY, DD/MM/YYYY, MM/DD/YYYY (if unambiguous).
    """
    value = value.strip()
    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        datetime.strptime(value, "%Y-%m-%d")  # validate
        return value
    # DD.MM.YYYY or DD/MM/YYYY
    for sep, fmt in [(".", "%d.%m.%Y"), ("/", "%d/%m/%Y")]:
        if sep in value:
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
    die(f"Cannot parse date '{value}'. Use YYYY-MM-DD or DD.MM.YYYY.")
    return ""  # unreachable


def _emit_result(result, args) -> None:
    """Emit command output using the resolved format."""
    output(result, _resolve_fmt(args))


def _read_optional_stdin_json() -> dict | None:
    """Read JSON from stdin when present, otherwise return None."""
    if sys.stdin.isatty():
        return None
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        die("Invalid JSON on stdin.")


def _read_stdin_json() -> dict:
    """Read and parse JSON from stdin, or die with helpful error."""
    body = _read_optional_stdin_json()
    if body is None:
        die("Pipe JSON body via stdin. Example: echo '{...}' | qbo <command> <entity>")
    return body


def _build_report_params(args) -> dict | None:
    """Build report query params from CLI args."""
    params = {}
    if args.start_date:
        params["start_date"] = _parse_date(args.start_date)
    if args.end_date:
        params["end_date"] = _parse_date(args.end_date)
    if args.date_macro:
        params["date_macro"] = args.date_macro
    if args.params:
        for param in args.params:
            if "=" not in param:
                die(f"Invalid param format '{param}'. Use key=value.")
            key, value = param.split("=", 1)
            params[key] = value
    return params or None
