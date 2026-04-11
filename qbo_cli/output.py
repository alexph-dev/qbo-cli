"""Output formatting helpers: text tables, JSON, TSV, report padding."""

from __future__ import annotations

import calendar
import json
import sys
from datetime import datetime

from qbo_cli.constants import REPORT_WIDTH


def _unwrap_entity_dict(data: dict) -> dict:
    """Unwrap entity payloads like {'Customer': {...}} to the inner object."""
    keys = list(data.keys())
    if len(keys) == 1 and isinstance(data[keys[0]], dict):
        return data[keys[0]]
    return data


def _first_list_value(data: dict) -> list | None:
    """Return the first list value in a dict, if present."""
    for value in data.values():
        if isinstance(value, list):
            return value
    return None


def _normalize_output_data(data, *, unwrap_entity: bool = False, extract_list: bool = False):
    """Apply shared output normalization for dict-based QBO responses."""
    if not isinstance(data, dict):
        return data

    normalized = _unwrap_entity_dict(data) if unwrap_entity else data
    if extract_list:
        list_value = _first_list_value(normalized)
        if list_value is not None:
            return list_value
    return normalized


def _has_nested_dict_list(data: dict) -> bool:
    """Return True when a dict contains at least one list of dicts."""
    return any(isinstance(v, list) and v and isinstance(v[0], dict) for v in data.values())


def output(data, fmt: str = "text") -> None:
    """Write result to stdout."""
    if fmt == "tsv":
        output_tsv(data)
    elif fmt == "text":
        output_text(data)
    else:
        _print_json_fallback(data)


def _truncate(s: str, maxlen: int) -> str:
    return s[: maxlen - 1] + "…" if len(s) > maxlen else s


def _select_table_columns(sample_row: dict) -> list:
    """Pick scalar keys from a row; fall back to first six keys if none qualify."""
    all_keys = list(sample_row.keys())
    scalar_keys = [k for k in all_keys if not isinstance(sample_row.get(k), (dict, list))]
    return scalar_keys or all_keys[:6]


def _compute_column_widths(rows: list, keys: list, max_width: int = 40) -> dict:
    """Compute per-column display widths capped at ``max_width``."""
    widths: dict = {}
    for k in keys:
        cell_width = max((len(_truncate(str(row.get(k, "")), max_width)) for row in rows), default=0)
        widths[k] = min(max(len(k), cell_width), max_width)
    return widths


def _render_table_header(keys: list, widths: dict) -> None:
    """Print column headers with an underline matching the header width."""
    header = "  ".join(k.ljust(widths[k]) for k in keys)
    print(header)
    print("─" * len(header))


def _render_table_row(row: dict, keys: list, widths: dict) -> None:
    """Print one data row with each cell truncated to its column width."""
    print("  ".join(_truncate(str(row.get(k, "")), widths[k]).ljust(widths[k]) for k in keys))


def _print_json_fallback(data) -> None:
    """Dump arbitrary data as pretty-printed JSON."""
    json.dump(data, sys.stdout, indent=2, default=str)
    print()


def output_text(data) -> None:
    """Human-readable table output."""
    data = _normalize_output_data(data, unwrap_entity=True)
    if isinstance(data, dict):
        data = _resolve_dict_payload(data)
        if data is None:
            return

    if not data:
        print("(no results)")
        return
    if not isinstance(data, list) or not isinstance(data[0], dict):
        _print_json_fallback(data)
        return

    _render_table(data)


def _resolve_dict_payload(data: dict):
    """Render or unwrap a dict payload; return None when fully consumed, else a list."""
    if not _has_nested_dict_list(data):
        _output_kv(data)
        return None
    inner = _normalize_output_data(data, extract_list=True)
    if isinstance(inner, dict):
        _output_kv(inner)
        return None
    return inner


def _render_table(rows: list) -> None:
    """Render a non-empty list of dicts as a fixed-width table with row count."""
    keys = _select_table_columns(rows[0])
    widths = _compute_column_widths(rows, keys)
    _render_table_header(keys, widths)
    for row in rows:
        _render_table_row(row, keys, widths)
    print(f"\n({len(rows)} rows)")


def _output_kv(data: dict, indent: int = 0) -> None:
    """Pretty-print a single entity as key-value pairs."""
    prefix = "  " * indent
    scalar_keys = [k for k, v in data.items() if not isinstance(v, (dict, list))]
    nested_keys = [k for k, v in data.items() if isinstance(v, (dict, list))]
    max_key = max((len(k) for k in scalar_keys), default=10)

    for k in scalar_keys:
        v = data[k]
        print(f"{prefix}{k:<{max_key}}  {v}")

    for k in nested_keys:
        v = data[k]
        if isinstance(v, dict):
            # Inline small nested dicts so flat entities stay on one screen.
            simple_vals = {sk: sv for sk, sv in v.items() if not isinstance(sv, (dict, list))}
            if simple_vals and len(simple_vals) <= 3:
                flat = ", ".join(f"{sk}={sv}" for sk, sv in simple_vals.items())
                print(f"{prefix}{k:<{max_key}}  {flat}")
            elif simple_vals:
                print(f"{prefix}{k}:")
                _output_kv(v, indent + 1)
        elif isinstance(v, list) and v:
            if isinstance(v[0], dict):
                print(f"{prefix}{k}: ({len(v)} items)")
            else:
                print(f"{prefix}{k:<{max_key}}  {v}")


def output_tsv(data) -> None:
    """Flatten list-of-dicts to TSV."""
    data = _normalize_output_data(data, extract_list=True)
    if isinstance(data, dict):
        data = [data]
    if not data:
        return
    if isinstance(data, list) and data and isinstance(data[0], dict):
        keys = list(data[0].keys())
        print("\t".join(keys))
        for row in data:
            print("\t".join(str(row.get(k, "")) for k in keys))
    else:
        _print_json_fallback(data)


def _format_amount(amount: float, currency: str = "") -> str:
    prefix = currency or ""
    if amount < 0:
        return f"-{prefix}{abs(amount):,.2f}"
    return f"{prefix}{amount:,.2f}"


def _is_month_start(d: datetime) -> bool:
    return d.day == 1


def _is_month_end(d: datetime) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def _format_date_range(start: str, end: str) -> str:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    s_clean = _is_month_start(s)
    e_clean = _is_month_end(e)

    if s.month == e.month and s.year == e.year:
        if s_clean and e_clean:
            return f"{s.strftime('%B')}, {s.year}"
        elif s_clean:
            return f"{s.strftime('%B')} 1-{e.day}, {s.year}"
        else:
            return f"{s.strftime('%B')} {s.day}-{e.day}, {s.year}"
    elif s.year == e.year:
        s_fmt = s.strftime("%B") if s_clean else f"{s.strftime('%B')} {s.day}"
        e_fmt = e.strftime("%B") if e_clean else f"{e.strftime('%B')} {e.day}"
        return f"{s_fmt}-{e_fmt}, {s.year}"
    else:
        s_fmt = s.strftime("%B %Y") if s_clean else f"{s.day} {s.strftime('%B %Y')}"
        e_fmt = e.strftime("%B %Y") if e_clean else f"{e.day} {e.strftime('%B %Y')}"
        return f"{s_fmt}-{e_fmt}"


def _pad_line(label: str, amt_str: str, prefix: str = "") -> str:
    total_len = len(prefix) + len(label) + len(amt_str)
    pad = max(1, REPORT_WIDTH - total_len)
    return f"{prefix}{label}{' ' * pad}{amt_str}"
