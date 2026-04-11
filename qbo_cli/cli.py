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
import os
import sys

from qbo_cli.auth import (
    TokenManager,
    cmd_auth_init,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    cmd_auth_refresh,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    cmd_auth_setup,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    cmd_auth_status,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
)
from qbo_cli.cli_options import (
    _build_report_params,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _emit_result,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _make_client,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _parse_date,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _read_optional_stdin_json,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _read_stdin_json,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _resolve_fmt,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
)
from qbo_cli.client import QBOClient  # noqa: F401  (re-exported for tests until wave-1 commit 13)
from qbo_cli.commands import (
    cmd_create,
    cmd_delete,
    cmd_get,
    cmd_query,
    cmd_raw,
    cmd_report,
    cmd_search,
    cmd_update,
    cmd_void,
)
from qbo_cli.config import Config
from qbo_cli.constants import (
    CONFIG_PATH,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    DEFAULT_REDIRECT,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    PROFILE_RE,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    QBO_DIR,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
)
from qbo_cli.errors import die
from qbo_cli.gl_report import (
    GLSection,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    GLTransaction,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _append_txn_lines,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _build_by_customer_report,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _build_report_lines,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _build_section_index,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _build_txns_report,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _collapse_tree,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _compute_subtotal,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _discover_account_tree,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _extract_dates_from_gl,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _find_gl_section,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _list_all_accounts,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _list_all_accounts_data,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _parse_gl_rows,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _parse_txn_from_row,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _print_account_tree,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _resolve_customer,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _txn_to_dict,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    cmd_gl_report,
)
from qbo_cli.output import (
    _first_list_value,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _format_amount,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _format_date_range,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _has_nested_dict_list,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _is_month_end,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _is_month_start,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _normalize_output_data,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _output_kv,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _pad_line,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _truncate,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _unwrap_entity_dict,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    output,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    output_text,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    output_tsv,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
)
from qbo_cli.parser import _build_parser
from qbo_cli.qbo_query import _qbo_escape  # noqa: F401  (re-exported for tests until wave-1 commit 13)
from qbo_cli.report_registry import (
    _REPORT_ALIAS_MAP,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    REPORT_REGISTRY,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _format_report_list,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _resolve_report_name,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
)


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
