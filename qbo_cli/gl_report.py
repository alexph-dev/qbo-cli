"""Hierarchical General Ledger report engine and `qbo gl-report` command."""

from __future__ import annotations

import functools
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from qbo_cli.cli_options import _make_client, _parse_date, _resolve_fmt
from qbo_cli.client import QBOClient
from qbo_cli.constants import REPORT_WIDTH
from qbo_cli.errors import die, err_print
from qbo_cli.output import _format_amount, _format_date_range, _pad_line, output
from qbo_cli.qbo_query import _qbo_escape


class GLTransaction:
    """A single GL transaction."""

    __slots__ = ("date", "txn_type", "txn_id", "num", "customer", "memo", "account", "amount")

    def __init__(self, date="", txn_type="", txn_id="", num="", customer="", memo="", account="", amount=0.0):
        self.date = date
        self.txn_type = txn_type
        self.txn_id = txn_id
        self.num = num
        self.customer = customer
        self.memo = memo
        self.account = account
        self.amount = amount


class GLSection:
    """Parsed GL account section with amounts and sub-sections."""

    def __init__(self, name: str, acct_id: str = ""):
        self.name = name
        self.id = acct_id
        self.direct_amount = 0.0
        self.direct_count = 0
        self.children: list["GLSection"] = []
        self.transactions: list[GLTransaction] = []

    @functools.cached_property
    def total_amount(self) -> float:
        return self.direct_amount + sum(c.total_amount for c in self.children)

    @functools.cached_property
    def total_count(self) -> int:
        return self.direct_count + sum(c.total_count for c in self.children)

    @functools.cached_property
    def all_transactions(self) -> list[GLTransaction]:
        """All transactions including from sub-sections."""
        txns = list(self.transactions)
        for c in self.children:
            txns.extend(c.all_transactions)
        return txns

    def direct_pair(self) -> tuple[float, int]:
        """(direct_amount, direct_count) — Tell, Don't Ask helper."""
        return self.direct_amount, self.direct_count

    def total_pair(self) -> tuple[float, int]:
        """(total_amount, total_count) — Tell, Don't Ask helper."""
        return self.total_amount, self.total_count


_ZERO_PAIR: tuple[float, int] = (0.0, 0)


def _direct_pair(section: GLSection | None) -> tuple[float, int]:
    """None-safe direct totals — collapses ``if section else`` ladders."""
    return section.direct_pair() if section else _ZERO_PAIR


def _total_pair(section: GLSection | None) -> tuple[float, int]:
    """None-safe rolled-up totals."""
    return section.total_pair() if section else _ZERO_PAIR


def _parse_txn_from_row(cols: list[dict]) -> GLTransaction | None:
    """Parse a Data row's ColData into a GLTransaction."""
    if not cols or cols[0].get("value", "") == "Beginning Balance":
        return None
    amt_str = cols[6].get("value", "") if len(cols) > 6 else ""
    if not amt_str:
        return None
    try:
        amount = float(amt_str)
    except ValueError:
        return None
    return GLTransaction(
        date=cols[0].get("value", "") if len(cols) > 0 else "",
        txn_type=cols[1].get("value", "") if len(cols) > 1 else "",
        txn_id=cols[1].get("id", "") if len(cols) > 1 else "",
        num=cols[2].get("value", "") if len(cols) > 2 else "",
        customer=cols[3].get("value", "") if len(cols) > 3 else "",
        memo=cols[4].get("value", "") if len(cols) > 4 else "",
        account=cols[5].get("value", "") if len(cols) > 5 else "",
        amount=amount,
    )


def _accumulate_direct_txns(section: GLSection, inner_rows: dict) -> None:
    """Append direct Data-row transactions from inner_rows onto section."""
    if not inner_rows or "Row" not in inner_rows:
        return
    for inner_row in inner_rows["Row"]:
        if inner_row.get("type") != "Data":
            continue
        txn = _parse_txn_from_row(inner_row.get("ColData", []))
        if txn is None:
            continue
        section.direct_amount += txn.amount
        section.direct_count += 1
        section.transactions.append(txn)


def _absorb_direct_placeholders(section: GLSection) -> None:
    """Fold any unnamed `__direct__` child sections into their parent."""
    kept: list[GLSection] = []
    for child in section.children:
        if child.name == "__direct__":
            section.direct_amount += child.direct_amount
            section.direct_count += child.direct_count
            section.transactions.extend(child.transactions)
        else:
            kept.append(child)
    section.children = kept


def _parse_gl_rows(rows_obj: dict) -> list[GLSection]:
    """Parse GL Rows object into list of GLSection."""
    sections: list[GLSection] = []
    if not rows_obj or "Row" not in rows_obj:
        return sections

    for row in rows_obj["Row"]:
        if row.get("type") != "Section":
            continue

        header_cols = row.get("Header", {}).get("ColData", [])
        name = header_cols[0].get("value", "").strip() if header_cols else ""
        acct_id = header_cols[0].get("id", "") if header_cols else ""
        inner_rows = row.get("Rows", {})

        if not name:
            placeholder = GLSection("__direct__", acct_id)
            _accumulate_direct_txns(placeholder, inner_rows)
            sections.append(placeholder)
            continue

        section = GLSection(name, acct_id)
        _accumulate_direct_txns(section, inner_rows)
        section.children = _parse_gl_rows(inner_rows)
        _absorb_direct_placeholders(section)
        sections.append(section)

    return sections


def _build_section_index(sections: list[GLSection]) -> dict[str, GLSection]:
    """Build flat name/id→section dict for O(1) lookups.

    Keys by both name and id to handle name collisions across hierarchy levels."""
    index = {}
    for s in sections:
        index[s.name] = s
        if s.id:
            index[s.id] = s
        index.update(_build_section_index(s.children))
    return index


def _find_gl_section(section_idx: dict[str, GLSection], name: str, acct_id: str = "") -> GLSection | None:
    """Find a GL section by id (preferred) or name, with suffix-match fallback."""
    if acct_id and acct_id in section_idx:
        return section_idx[acct_id]
    if name in section_idx:
        return section_idx[name]
    for key in section_idx:
        if key.endswith(f" {name}"):
            return section_idx[key]
    return None


def _extract_dates_from_gl(gl_data: dict) -> tuple[str | None, str | None]:
    """Extract earliest and latest transaction dates from raw GL data."""
    dates = []

    def walk(rows_obj):
        if not rows_obj or "Row" not in rows_obj:
            return
        for row in rows_obj["Row"]:
            if row.get("type") == "Data":
                cols = row.get("ColData", [])
                if cols:
                    val = cols[0].get("value", "")
                    if len(val) == 10 and val[4] == "-" and val[7] == "-":
                        dates.append(val)
            elif row.get("type") == "Section":
                walk(row.get("Rows", {}))

    walk(gl_data.get("Rows", {}))
    if not dates:
        return None, None
    dates.sort()
    return dates[0], dates[-1]


def _discover_account_tree(client: "QBOClient", account_ref: str) -> dict:
    """Build account tree from QBO by fetching sub-accounts under a parent.
    account_ref can be a numeric ID or account name (fuzzy match).
    """
    if account_ref.isdigit():
        parent_id = account_ref
        safe_ref = _qbo_escape(account_ref)
        accts = client.query(f"SELECT Id, Name, FullyQualifiedName FROM Account WHERE Id = '{safe_ref}'")
        parent_name = (
            accts[0].get("FullyQualifiedName", accts[0].get("Name", f"Account {account_ref}"))
            if accts
            else f"Account {account_ref}"
        )
    else:
        safe_ref = _qbo_escape(account_ref)
        accts = client.query(f"SELECT Id, Name, FullyQualifiedName FROM Account WHERE Name LIKE '%{safe_ref}%'")
        if not accts:
            die(f"No account found matching '{account_ref}'")
        match = next((a for a in accts if a["Name"].lower() == account_ref.lower()), accts[0])
        parent_id = match["Id"]
        parent_name = match.get("FullyQualifiedName", match["Name"])

    all_accts = client.query("SELECT Id, Name, FullyQualifiedName, SubAccount, ParentRef FROM Account")

    children_by_parent = defaultdict(list)
    for a in all_accts:
        pr = a.get("ParentRef", {})
        if isinstance(pr, dict) and pr.get("value"):
            children_by_parent[pr["value"]].append(a)

    def build_children(pid: str) -> list[dict]:
        kids = [
            {"name": a["Name"], "id": a["Id"], "children": build_children(a["Id"])} for a in children_by_parent[pid]
        ]
        kids.sort(key=lambda x: x["name"])
        return kids

    return {
        "name": parent_name.split(":")[-1].strip(),
        "id": parent_id,
        "children": build_children(parent_id),
    }


def _list_all_accounts_data(client: "QBOClient") -> dict:
    """Return all top-level accounts grouped by type."""
    all_accts = client.query("SELECT Id, Name, FullyQualifiedName, AccountType, SubAccount, ParentRef FROM Account")

    children_by_parent = defaultdict(list)
    for a in all_accts:
        pr = a.get("ParentRef", {})
        if isinstance(pr, dict) and pr.get("value"):
            children_by_parent[pr["value"]].append(a)

    def count_descendants(pid: str) -> int:
        return sum(1 + count_descendants(a["Id"]) for a in children_by_parent[pid])

    top = [a for a in all_accts if not a.get("SubAccount", False)]
    top.sort(key=lambda a: (a.get("AccountType", ""), a.get("Name", "")))

    groups = []
    current_group = None
    for a in top:
        atype = a.get("AccountType", "Other")
        desc = count_descendants(a["Id"])
        if current_group is None or current_group["type"] != atype:
            current_group = {"type": atype, "accounts": []}
            groups.append(current_group)
        current_group["accounts"].append(
            {
                "id": a["Id"],
                "name": a["Name"],
                "sub_account_count": desc,
            }
        )

    return {
        "groups": groups,
        "top_level_count": len(top),
        "total_count": len(all_accts),
    }


def _list_all_accounts(client: "QBOClient") -> None:
    """Print all top-level accounts grouped by type."""
    account_data = _list_all_accounts_data(client)
    for index, group in enumerate(account_data["groups"]):
        if index > 0:
            print()
        print(f"── {group['type']} ──")
        for account in group["accounts"]:
            desc = account["sub_account_count"]
            sub_str = f"  ({desc} sub-accounts)" if desc else ""
            print(f"  {account['id']:>15}  {account['name']}{sub_str}")

    print(f"\n{account_data['top_level_count']} top-level accounts, {account_data['total_count']} total")


def _print_account_tree(node: dict, indent: int = 0):
    """Print account tree."""
    prefix = "  " * indent
    marker = "└─ " if indent > 0 else ""
    print(f"{prefix}{marker}{node['name']} (ID: {node['id']})")
    for child in node["children"]:
        _print_account_tree(child, indent + 1)


def _resolve_customer(client: "QBOClient", name: str) -> tuple[str, str]:
    """Resolve customer display name to (id, full_name)."""
    if name.isdigit():
        data = client.get("Customer", name)
        customer = data.get("Customer", data)
        return name, customer.get("FullyQualifiedName", customer.get("DisplayName", name))

    # Exact then fuzzy
    safe_name = _qbo_escape(name)
    customers = client.query(
        f"SELECT Id, DisplayName, FullyQualifiedName FROM Customer WHERE DisplayName = '{safe_name}'"
    )
    if not customers:
        customers = client.query(
            f"SELECT Id, DisplayName, FullyQualifiedName FROM Customer WHERE DisplayName LIKE '%{safe_name}%'"
        )
    if not customers:
        die(f"No customer found matching '{name}'")
    if len(customers) > 1:
        err_print(f"Multiple customers found for '{name}':")
        for customer in customers:
            err_print(f"  ID={customer['Id']}  Name={customer.get('FullyQualifiedName', customer['DisplayName'])}")
        err_print("Using first match.")
    for customer in customers:
        if customer.get("DisplayName", "").lower() == name.lower():
            return customer["Id"], customer.get("FullyQualifiedName", customer["DisplayName"])
    first_match = customers[0]
    return first_match["Id"], first_match.get("FullyQualifiedName", first_match["DisplayName"])


def _compute_subtotal(section_idx: dict[str, GLSection], node: dict) -> tuple[float, int]:
    """Compute total for a tree node (own + children, recursively)."""
    section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
    if not node["children"]:
        return _total_pair(section)

    total_amt, total_cnt = _direct_pair(section)
    for child in node["children"]:
        c_amt, c_cnt = _compute_subtotal(section_idx, child)
        total_amt += c_amt
        total_cnt += c_cnt
    return total_amt, total_cnt


@dataclass(frozen=True)
class _RenderCtx:
    """Bundle of values that travel together through the GL render pipeline."""

    section_idx: dict[str, GLSection]
    currency: str
    expanded: bool


def _format_txn_lines(txns: list[GLTransaction], currency: str, indent: int) -> list[str]:
    """Return formatted transaction lines (sorted by date) for ``txns``."""
    prefix = "  " * indent
    return [
        _pad_line(
            f"{t.date}  {t.txn_type:<12s} {(t.memo[:40] + '…') if len(t.memo) > 40 else t.memo}",
            _format_amount(t.amount, currency),
            prefix,
        )
        for t in sorted(txns, key=lambda x: x.date)
    ]


def _render_node_lines(ctx: _RenderCtx, node: dict, indent: int) -> list[str]:
    """Pure renderer: return the lines for ``node`` and its descendants."""
    section = _find_gl_section(ctx.section_idx, node["name"], node.get("id", ""))
    prefix = "  " * indent

    # Leaf node: emit a single padded line plus optional expanded txns.
    if not node["children"]:
        amt, cnt = _total_pair(section)
        if cnt == 0 and not amt:
            return []
        out = [_pad_line(f"{node['name']} ({cnt})", _format_amount(amt, ctx.currency), prefix)]
        if ctx.expanded and section:
            out.extend(_format_txn_lines(section.all_transactions, ctx.currency, indent + 1))
        return out

    # Branch node: header + recursive children + subtotal footer.
    subtotal_amt, subtotal_cnt = _compute_subtotal(ctx.section_idx, node)
    if subtotal_cnt == 0 and not subtotal_amt:
        return []

    own_amt, own_cnt = _direct_pair(section)
    out = []
    if own_cnt > 0:
        out.append(_pad_line(f"{node['name']} ({own_cnt})", _format_amount(own_amt, ctx.currency), prefix))
        if ctx.expanded and section:
            out.extend(_format_txn_lines(section.transactions, ctx.currency, indent + 1))
    else:
        out.append(f"{prefix}{node['name']}")

    for child in node["children"]:
        out.extend(_render_node_lines(ctx, child, indent + 1))

    out.append(_pad_line(f"Total for {node['name']}", _format_amount(subtotal_amt, ctx.currency), prefix))
    return out


def _build_report_lines(
    section_idx: dict[str, GLSection],
    node: dict,
    currency: str,
    expanded: bool = False,
) -> list[str]:
    """Render a hierarchical GL report rooted at ``node`` into text lines."""
    ctx = _RenderCtx(section_idx=section_idx, currency=currency, expanded=expanded)
    return _render_node_lines(ctx, node, indent=0)


def _build_txns_report(section_idx: dict[str, GLSection], node: dict, currency: str) -> list[str]:
    """Flat list of all transactions sorted by date."""
    section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
    if not section:
        return ["(no transactions)"]

    txns = section.all_transactions
    if not txns:
        return ["(no transactions)"]

    txns.sort(key=lambda t: t.date)

    lines = []
    # Header
    lines.append(f"{'Date':<12s} {'Type':<14s} {'Amount':>14s}  {'Account'}")
    lines.append("─" * REPORT_WIDTH)

    for t in txns:
        acct_short = t.account.split(":")[-1] if t.account else ""
        amt_str = _format_amount(t.amount, currency)
        lines.append(f"{t.date:<12s} {t.txn_type:<14s} {amt_str:>14s}  {acct_short}")
        if t.memo:
            memo = t.memo[:68] + "…" if len(t.memo) > 68 else t.memo
            lines.append(f"{'':12s} {memo}")

    lines.append("─" * REPORT_WIDTH)
    total = sum(t.amount for t in txns)
    lines.append(f"{'TOTAL':<12s} {'':14s} {_format_amount(total, currency):>14s}  ({len(txns)} transactions)")

    return lines


def _collapse_tree(node: dict) -> dict:
    """Collapse a tree to a single node (no children) for --no-sub mode."""
    return {"name": node["name"], "id": node["id"], "children": []}


def _customer_group_key(customer: str, prefix: str) -> str:
    """Resolve the bucket key for ``customer`` under an optional ``prefix``.

    With no prefix, customers group by their full name. With a prefix, names
    that descend from it collapse to ``prefix + first_child`` (one level
    below); names that do not descend from it group as-is.
    """
    if not prefix or not customer.startswith(prefix):
        return customer
    first_child = customer[len(prefix) :].split(":", 1)[0]
    return prefix + first_child


def _group_txns_by_customer(
    txns: list[GLTransaction], customer_filter: str
) -> tuple[dict[str, list[GLTransaction]], list[GLTransaction]]:
    """Group transactions by customer key.

    Returns ``(groups, skipped_parent_txns)`` where ``skipped_parent_txns``
    holds transactions whose customer matches ``customer_filter`` exactly
    (the parent itself), so callers can render them in a separate ``direct``
    bucket.
    """
    parent = customer_filter.rstrip(":")
    prefix = parent + ":" if parent else ""

    groups: dict[str, list[GLTransaction]] = defaultdict(list)
    skipped_parent_txns: list[GLTransaction] = []

    for txn in txns:
        customer = txn.customer or "(no customer)"
        if prefix and customer == parent:
            skipped_parent_txns.append(txn)
            continue
        groups[_customer_group_key(customer, prefix)].append(txn)

    return groups, skipped_parent_txns


def _sort_customer_groups(groups: dict[str, list[GLTransaction]], sort_by: str) -> list[str]:
    """Order customer keys alphabetically or by absolute group total."""
    if sort_by == "amount":
        return sorted(
            groups,
            key=lambda customer: abs(sum(txn.amount for txn in groups[customer])),
            reverse=True,
        )
    return sorted(groups)


def _build_by_customer_report(
    section_idx: dict[str, GLSection], node: dict, currency: str, customer_filter: str = "", sort_by: str = "alpha"
) -> list[str]:
    """Group all transactions by customer and show per-customer subtotals.

    customer_filter: if set, group at depth=1 below this customer prefix
                     (e.g. "Parent" groups Parent:Team:Leaf → Parent:Team, skips Parent itself)
    sort_by: "alpha" (alphabetical) or "amount" (absolute total descending)
    """

    section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
    if not section:
        return ["(no transactions)"]

    txns = section.all_transactions
    if not txns:
        return ["(no transactions)"]

    groups, skipped_parent_txns = _group_txns_by_customer(txns, customer_filter)
    sorted_customers = _sort_customer_groups(groups, sort_by)

    lines = [node["name"], ""]
    for customer in sorted_customers:
        customer_txns = groups[customer]
        customer_total = sum(txn.amount for txn in customer_txns)
        lines.append(_pad_line(f"{customer} ({len(customer_txns)})", _format_amount(customer_total, currency)))

    if skipped_parent_txns:
        parent_total = sum(txn.amount for txn in skipped_parent_txns)
        lines.append("")
        lines.append(
            _pad_line(
                f"({customer_filter} direct) ({len(skipped_parent_txns)})",
                _format_amount(parent_total, currency),
            )
        )

    lines.append("")
    grand_total = sum(txn.amount for txn in txns)
    lines.append(_pad_line(f"TOTAL ({len(txns)})", _format_amount(grand_total, currency)))

    return lines


def _serialize_txn(txn: GLTransaction) -> dict:
    """Serialize a GLTransaction to a plain dict."""
    return {
        "date": txn.date,
        "type": txn.txn_type,
        "id": txn.txn_id,
        "num": txn.num,
        "customer": txn.customer,
        "memo": txn.memo,
        "account": txn.account,
        "amount": txn.amount,
    }


def _handle_list_accounts_mode(args, client: "QBOClient", out_mode: str) -> None:
    """Handle the `--list-accounts` branch of `gl-report`."""
    if out_mode not in ("text", "json"):
        die("gl-report --list-accounts supports text or json output only.")
    if args.account:
        tree = _discover_account_tree(client, args.account)
        if out_mode == "json":
            output(tree, out_mode)
        else:
            _print_account_tree(tree)
        return
    if out_mode == "json":
        output(_list_all_accounts_data(client), out_mode)
    else:
        _list_all_accounts(client)


def _resolve_gl_date_window(args) -> tuple[str, str, bool]:
    """Return (start_date, end_date, auto_start_flag) for the GL fetch window."""
    end_date = _parse_date(args.end) if args.end else datetime.now().strftime("%Y-%m-%d")
    start_date = _parse_date(args.start) if args.start else "2000-01-01"
    return start_date, end_date, args.start is None


def _fetch_gl_data(client: "QBOClient", start_date: str, end_date: str, method: str, cust_id: str | None) -> dict:
    """Fetch GL report from QBO and bail out if it has no data."""
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "accounting_method": method,
    }
    if cust_id:
        params["customer"] = cust_id
    gl_data = client.report("GeneralLedger", params)
    for opt in gl_data.get("Header", {}).get("Option", []):
        if opt.get("Name") == "NoReportData" and opt.get("Value") == "true":
            die("No data found for the specified filters.")
    return gl_data


def _serialize_section_tree(section_idx: dict[str, GLSection], node: dict) -> dict:
    """Serialize an account-tree node into a JSON-friendly dict using section_idx."""
    section = _find_gl_section(section_idx, node["name"], node.get("id", ""))
    result: dict = {"name": node["name"], "id": node["id"]}
    if not node["children"]:
        result["amount"], result["count"] = _total_pair(section)
        txns = section.all_transactions if section else []
        if txns:
            result["transactions"] = [_serialize_txn(t) for t in sorted(txns, key=lambda x: x.date)]
        return result

    result["direct_amount"], result["direct_count"] = _direct_pair(section)
    result["total_amount"], result["total_count"] = _compute_subtotal(section_idx, node)
    result["children"] = [_serialize_section_tree(section_idx, c) for c in node["children"]]
    if section and section.transactions:
        result["transactions"] = [_serialize_txn(t) for t in sorted(section.transactions, key=lambda x: x.date)]
    return result


def cmd_gl_report(args, config, token_mgr):
    """Generate a hierarchical General Ledger report."""
    # Phase 1: setup client and resolve output format.
    client = _make_client(config, token_mgr)
    out_mode = _resolve_fmt(args)

    # Phase 2: short-circuit on --list-accounts (separate, non-report mode).
    if args.list_accounts:
        _handle_list_accounts_mode(args, client, out_mode)
        return

    # Phase 3: resolve inputs (customer, dates, account tree, GL data).
    cust_id, cust_name = (None, None)
    if args.customer:
        cust_id, cust_name = _resolve_customer(client, args.customer)

    start_date, end_date, auto_start = _resolve_gl_date_window(args)

    if not args.account:
        die("Account is required. Use -a/--account (ID or name). Use --list-accounts to explore.")
    account_tree = _discover_account_tree(client, args.account)

    gl_data = _fetch_gl_data(client, start_date, end_date, args.method, cust_id)

    gl_sections = _parse_gl_rows(gl_data.get("Rows", {}))
    section_idx = _build_section_index(gl_sections)

    # Phase 4: shape the tree and date window for display.
    if args.no_sub:
        account_tree = _collapse_tree(account_tree)

    display_start = start_date
    if auto_start:
        actual_first, _ = _extract_dates_from_gl(gl_data)
        if actual_first:
            display_start = actual_first

    # Phase 5: validate output mode (tsv unsupported for GL).
    if out_mode == "tsv":
        die("gl-report does not support tsv output. Use text, json, txns, or expanded.")

    # Phase 6: compute presentation values shared across renderers.
    title = f"General Ledger Report - {cust_name}" if cust_name else "General Ledger Report"
    date_range = _format_date_range(display_start, end_date)
    currency = args.currency
    total_amt, _ = _compute_subtotal(section_idx, account_tree)

    if args.by_customer and out_mode in ("json", "txns"):
        err_print("Warning: --by-customer is only supported with text/expanded output. Ignoring -g flag.")

    # Phase 7: dispatch on output mode.
    if out_mode == "json":
        report_data: dict = {
            "start_date": display_start,
            "end_date": end_date,
            "method": args.method,
            "account": _serialize_section_tree(section_idx, account_tree),
            "total": total_amt,
        }
        if cust_name:
            report_data["customer"] = cust_name
            report_data["customer_id"] = cust_id
        output(report_data, out_mode)
        return

    if out_mode == "txns":
        lines = [title, date_range, ""]
        lines.extend(_build_txns_report(section_idx, account_tree, currency))
        print("\n".join(lines))
        return

    if args.by_customer:
        lines = [title, date_range, ""]
        lines.extend(
            _build_by_customer_report(
                section_idx,
                account_tree,
                currency,
                customer_filter=cust_name or "",
                sort_by=args.sort,
            )
        )
        print("\n".join(lines))
        return

    expanded = out_mode == "expanded"
    lines = [title, date_range, ""]
    lines.extend(_build_report_lines(section_idx, account_tree, currency, expanded=expanded))
    lines.append("")
    lines.append(_pad_line("TOTAL", _format_amount(total_amt, currency)))
    print("\n".join(lines))
