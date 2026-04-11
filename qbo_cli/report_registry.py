"""Canonical QBO report types, aliases, and resolution helpers."""

from __future__ import annotations

from qbo_cli.errors import err_print

# Canonical QBO report types with descriptions and short aliases.
# Keys are canonical API names; values are (description, [aliases]).
REPORT_REGISTRY: dict[str, tuple[str, list[str]]] = {
    "ProfitAndLoss": ("Income and expenses summary", ["PnL", "P&L"]),
    "ProfitAndLossDetail": ("Detailed income and expenses", ["PnLDetail"]),
    "BalanceSheet": ("Assets, liabilities, and equity", ["BS"]),
    "BalanceSheetDetail": ("Detailed balance sheet", ["BSDetail"]),
    "CashFlow": ("Cash inflows and outflows", ["CF"]),
    "GeneralLedger": ("All transactions by account", ["GL"]),
    "TrialBalance": ("Debit and credit totals by account", ["TB"]),
    "AccountList": ("Chart of accounts listing", ["Accounts", "CoA"]),
    "TransactionList": ("All transactions flat list", ["TxnList"]),
    "CustomerIncome": ("Income by customer", []),
    "CustomerBalance": ("Outstanding balances by customer", []),
    "CustomerBalanceDetail": ("Detailed customer balances", []),
    "CustomerSales": ("Sales by customer", []),
    "AgedReceivables": ("Outstanding receivables by age", ["AR"]),
    "AgedReceivableDetail": ("Detailed aged receivables", ["ARDetail"]),
    "AgedPayables": ("Outstanding payables by age", ["AP"]),
    "AgedPayableDetail": ("Detailed aged payables", ["APDetail"]),
    "VendorBalance": ("Outstanding balances by vendor", []),
    "VendorBalanceDetail": ("Detailed vendor balances", []),
    "VendorExpenses": ("Expenses by vendor", []),
    "ItemSales": ("Sales by item/product", []),
    "DepartmentSales": ("Sales by department", []),
    "ClassSales": ("Sales by class", []),
}

# Build case-insensitive alias -> canonical name lookup.
_REPORT_ALIAS_MAP: dict[str, str] = {}
for _canonical, (_desc, _aliases) in REPORT_REGISTRY.items():
    _REPORT_ALIAS_MAP[_canonical.lower()] = _canonical
    for _alias in _aliases:
        _REPORT_ALIAS_MAP[_alias.lower()] = _canonical


def _resolve_report_name(name: str) -> str:
    """Resolve a report name or alias to the canonical QBO API report name.

    Args:
        name: Report name or alias (case-insensitive)

    Returns:
        Canonical report name for the QBO API
    """
    canonical = _REPORT_ALIAS_MAP.get(name.lower())
    if canonical:
        return canonical
    known = ", ".join(sorted(REPORT_REGISTRY))
    err_print(
        f"Warning: '{name}' is not a known report type. "
        f"Passing through to API.\nKnown reports: {known}\n"
        f"Run 'qbo report --list' to see all reports with aliases."
    )
    return name


def _format_report_list() -> str:
    """Format the report registry as a readable table for --list output."""
    lines = []
    for canonical, (desc, aliases) in REPORT_REGISTRY.items():
        alias_str = f" ({', '.join(aliases)})" if aliases else ""
        lines.append(f"  {canonical:<28} {desc}{alias_str}")
    return "Available reports:\n" + "\n".join(lines)
