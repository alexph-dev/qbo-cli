"""Entity-level CLI command handlers (query, CRUD, report, raw)."""

from __future__ import annotations

import json

from qbo_cli.cli_options import (
    _build_report_params,
    _emit_result,
    _make_client,
    _read_optional_stdin_json,
    _read_stdin_json,
)
from qbo_cli.errors import die
from qbo_cli.report_registry import _format_report_list, _resolve_report_name


def cmd_query(args, config, token_mgr):
    client = _make_client(config, token_mgr)
    results = client.query(args.sql, max_pages=args.max_pages)
    _emit_result(results, args)


def _build_row_matcher(needle: str, *, case_sensitive: bool):
    """Return a predicate that finds ``needle`` in a row's JSON serialization."""
    if case_sensitive:
        return lambda row: needle in json.dumps(row, default=str, ensure_ascii=False)
    folded = needle.casefold()
    return lambda row: folded in json.dumps(row, default=str, ensure_ascii=False).casefold()


def cmd_search(args, config, token_mgr):
    client = _make_client(config, token_mgr)
    results = client.query(args.sql, max_pages=args.max_pages)
    matcher = _build_row_matcher(args.text, case_sensitive=args.case_sensitive)
    matches = [row for row in results if matcher(row)]
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
