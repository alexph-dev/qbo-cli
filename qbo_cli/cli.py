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
import json
import os
import sys

from qbo_cli import __version__
from qbo_cli.auth import (
    TokenManager,
    cmd_auth_init,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    cmd_auth_refresh,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    cmd_auth_setup,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    cmd_auth_status,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
)
from qbo_cli.cli_options import (
    _build_report_params,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _emit_result,
    _make_client,
    _parse_date,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _read_optional_stdin_json,
    _read_stdin_json,
    _resolve_fmt,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
)
from qbo_cli.client import QBOClient  # noqa: F401  (re-exported for tests until wave-1 commit 13)
from qbo_cli.config import Config
from qbo_cli.constants import (
    CONFIG_PATH,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    DEFAULT_MAX_PAGES,
    DEFAULT_REDIRECT,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    FMT_HELP,
    GL_OUTPUT_FORMATS,
    OUTPUT_FORMATS,
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
from qbo_cli.qbo_query import _qbo_escape  # noqa: F401  (re-exported for tests until wave-1 commit 13)
from qbo_cli.report_registry import (
    _REPORT_ALIAS_MAP,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    REPORT_REGISTRY,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _format_report_list,  # noqa: F401  (re-exported for tests until wave-1 commit 13)
    _resolve_report_name,
)

# ─── Entity Commands ─────────────────────────────────────────────────────────


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
