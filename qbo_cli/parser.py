"""Top-level argparse parser builder for the qbo CLI."""

from __future__ import annotations

import argparse

from qbo_cli import __version__
from qbo_cli.constants import DEFAULT_MAX_PAGES, FMT_HELP, GL_OUTPUT_FORMATS, OUTPUT_FORMATS


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
