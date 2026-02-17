"""Tests for GL parsing functions using fixture data."""

from __future__ import annotations

import pytest

from qbo_cli.cli import (
    GLSection,
    _build_section_index,
    _compute_subtotal,
    _extract_dates_from_gl,
    _find_gl_section,
    _parse_gl_rows,
    _parse_txn_from_row,
)


# ─── _parse_txn_from_row ─────────────────────────────────────────────────────


class TestParseTxnFromRow:
    def test_valid_7col_row(self):
        cols = [
            {"value": "2025-01-15"},
            {"value": "Invoice", "id": "5001"},
            {"value": "1001"},
            {"value": "Acme Corp"},
            {"value": "Consulting"},
            {"value": "Revenue"},
            {"value": "5000.00"},
        ]
        txn = _parse_txn_from_row(cols)
        assert txn is not None
        assert txn.date == "2025-01-15"
        assert txn.txn_type == "Invoice"
        assert txn.txn_id == "5001"
        assert txn.amount == 5000.0

    def test_beginning_balance_skip(self):
        cols = [{"value": "Beginning Balance"}]
        assert _parse_txn_from_row(cols) is None

    def test_short_row(self):
        cols = [{"value": "2025-01-15"}, {"value": "Invoice"}]
        # len(cols) < 7, so cols[6] would fail; amount will be ""
        assert _parse_txn_from_row(cols) is None

    def test_empty_amount(self):
        cols = [
            {"value": "2025-01-15"},
            {"value": "Invoice", "id": "5001"},
            {"value": "1001"},
            {"value": "Acme"},
            {"value": "memo"},
            {"value": "Revenue"},
            {"value": ""},
        ]
        assert _parse_txn_from_row(cols) is None

    def test_empty_cols(self):
        assert _parse_txn_from_row([]) is None

    def test_non_numeric_amount(self):
        cols = [
            {"value": "2025-01-15"},
            {"value": "Invoice", "id": "5001"},
            {"value": ""},
            {"value": ""},
            {"value": ""},
            {"value": ""},
            {"value": "not-a-number"},
        ]
        assert _parse_txn_from_row(cols) is None


# ─── _parse_gl_rows ──────────────────────────────────────────────────────────


class TestParseGlRows:
    def test_nested_fixture(self, gl_fixture):
        rows_obj = gl_fixture.get("Rows", {})
        sections = _parse_gl_rows(rows_obj)
        assert len(sections) == 2  # Revenue and Expenses

        revenue = sections[0]
        assert revenue.name == "Revenue"
        assert revenue.id == "100"
        # Revenue has 2 child sections + 1 direct transaction (JE)
        assert len(revenue.children) == 2
        assert revenue.children[0].name == "Consulting Revenue"
        assert revenue.children[1].name == "Product Revenue"

    def test_transaction_counts(self, gl_fixture):
        rows_obj = gl_fixture.get("Rows", {})
        sections = _parse_gl_rows(rows_obj)

        consulting = sections[0].children[0]
        assert consulting.direct_count == 3
        assert consulting.direct_amount == pytest.approx(15700.0)

        product = sections[0].children[1]
        assert product.direct_count == 1
        assert product.direct_amount == pytest.approx(12000.0)

    def test_empty_rows(self):
        assert _parse_gl_rows({}) == []
        assert _parse_gl_rows(None) == []
        assert _parse_gl_rows({"Row": []}) == []

    def test_direct_transactions_on_parent(self, gl_fixture):
        """Revenue section has a direct JE transaction (not in a child)."""
        rows_obj = gl_fixture.get("Rows", {})
        sections = _parse_gl_rows(rows_obj)
        revenue = sections[0]
        # The JE is a direct transaction on Revenue
        assert revenue.direct_count == 1
        assert revenue.direct_amount == pytest.approx(-500.0)

    def test_expenses_section(self, gl_fixture):
        rows_obj = gl_fixture.get("Rows", {})
        sections = _parse_gl_rows(rows_obj)
        expenses = sections[1]
        assert expenses.name == "Expenses"
        assert expenses.direct_count == 2
        assert expenses.direct_amount == pytest.approx(339.99)


# ─── _extract_dates_from_gl ──────────────────────────────────────────────────


class TestExtractDatesFromGl:
    def test_fixture_dates(self, gl_fixture):
        earliest, latest = _extract_dates_from_gl(gl_fixture)
        assert earliest == "2025-01-15"
        assert latest == "2025-06-01"

    def test_empty_data(self):
        earliest, latest = _extract_dates_from_gl({})
        assert earliest is None
        assert latest is None

    def test_no_rows(self):
        earliest, latest = _extract_dates_from_gl({"Rows": {}})
        assert earliest is None
        assert latest is None


# ─── _compute_subtotal ────────────────────────────────────────────────────────


class TestComputeSubtotal:
    def test_leaf_node(self, gl_fixture):
        sections = _parse_gl_rows(gl_fixture.get("Rows", {}))
        idx = _build_section_index(sections)
        node = {"name": "Consulting Revenue", "id": "101", "children": []}
        amt, cnt = _compute_subtotal(idx, node)
        assert amt == pytest.approx(15700.0)
        assert cnt == 3

    def test_parent_with_children(self, gl_fixture):
        sections = _parse_gl_rows(gl_fixture.get("Rows", {}))
        idx = _build_section_index(sections)
        node = {
            "name": "Revenue",
            "id": "100",
            "children": [
                {"name": "Consulting Revenue", "id": "101", "children": []},
                {"name": "Product Revenue", "id": "102", "children": []},
            ],
        }
        amt, cnt = _compute_subtotal(idx, node)
        # Consulting (15700) + Product (12000) + direct on Revenue (-500)
        assert amt == pytest.approx(27200.0)
        assert cnt == 5  # 3 + 1 + 1

    def test_empty_tree(self):
        idx = {}
        node = {"name": "Missing", "id": "999", "children": []}
        amt, cnt = _compute_subtotal(idx, node)
        assert amt == 0.0
        assert cnt == 0


# ─── GLSection cached_property ───────────────────────────────────────────────


class TestGLSectionCachedProperty:
    def test_total_amount_leaf(self):
        s = GLSection("Test", "1")
        s.direct_amount = 100.0
        assert s.total_amount == 100.0

    def test_total_amount_with_children(self):
        parent = GLSection("Parent", "1")
        parent.direct_amount = 50.0
        child = GLSection("Child", "2")
        child.direct_amount = 30.0
        parent.children = [child]
        assert parent.total_amount == 80.0

    def test_total_count(self):
        parent = GLSection("Parent", "1")
        parent.direct_count = 2
        child = GLSection("Child", "2")
        child.direct_count = 3
        parent.children = [child]
        assert parent.total_count == 5

    def test_all_transactions(self):
        from qbo_cli.cli import GLTransaction

        parent = GLSection("Parent", "1")
        t1 = GLTransaction(date="2025-01-01", amount=100.0)
        parent.transactions = [t1]
        child = GLSection("Child", "2")
        t2 = GLTransaction(date="2025-02-01", amount=200.0)
        child.transactions = [t2]
        parent.children = [child]
        assert len(parent.all_transactions) == 2
