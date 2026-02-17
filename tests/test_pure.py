"""Tests for pure helper functions — zero mocking needed."""

from __future__ import annotations

import pytest

from qbo_cli.cli import (
    GLSection,
    GLTransaction,
    _build_section_index,
    _collapse_tree,
    _find_gl_section,
    _format_amount,
    _format_date_range,
    _is_month_end,
    _is_month_start,
    _pad_line,
    _qbo_escape,
    _truncate,
    _txn_to_dict,
)
from datetime import datetime


# ─── _qbo_escape ──────────────────────────────────────────────────────────────


class TestQboEscape:
    def test_single_quote(self):
        assert _qbo_escape("O'Brien") == "O''Brien"

    def test_percent_stripped(self):
        assert _qbo_escape("50%") == "50"

    def test_empty_string(self):
        assert _qbo_escape("") == ""

    def test_combined(self):
        assert _qbo_escape("O'Brien 50%") == "O''Brien 50"

    def test_multiple_quotes(self):
        assert _qbo_escape("it's a 'test'") == "it''s a ''test''"

    def test_no_special_chars(self):
        assert _qbo_escape("plain text") == "plain text"


# ─── _format_date_range ──────────────────────────────────────────────────────


class TestFormatDateRange:
    def test_full_month(self):
        assert _format_date_range("2025-01-01", "2025-01-31") == "January, 2025"

    def test_partial_month_from_start(self):
        assert _format_date_range("2025-01-01", "2025-01-15") == "January 1-15, 2025"

    def test_partial_month_mid(self):
        assert _format_date_range("2025-01-10", "2025-01-20") == "January 10-20, 2025"

    def test_cross_month_same_year_full(self):
        result = _format_date_range("2025-01-01", "2025-03-31")
        assert result == "January-March, 2025"

    def test_cross_month_same_year_partial(self):
        result = _format_date_range("2025-01-15", "2025-03-20")
        assert result == "January 15-March 20, 2025"

    def test_cross_year(self):
        result = _format_date_range("2024-11-01", "2025-02-28")
        assert result == "November 2024-February 2025"

    def test_cross_year_partial(self):
        result = _format_date_range("2024-11-15", "2025-02-10")
        assert result == "15 November 2024-10 February 2025"

    def test_february_non_leap(self):
        assert _format_date_range("2025-02-01", "2025-02-28") == "February, 2025"

    def test_leap_year_february(self):
        assert _format_date_range("2024-02-01", "2024-02-29") == "February, 2024"

    def test_same_day(self):
        result = _format_date_range("2025-01-15", "2025-01-15")
        assert "January" in result
        assert "2025" in result


# ─── _is_month_start / _is_month_end ─────────────────────────────────────────


class TestIsMonthStart:
    def test_jan_1(self):
        assert _is_month_start(datetime(2025, 1, 1)) is True

    def test_jan_2(self):
        assert _is_month_start(datetime(2025, 1, 2)) is False

    def test_dec_1(self):
        assert _is_month_start(datetime(2025, 12, 1)) is True


class TestIsMonthEnd:
    def test_jan_31(self):
        assert _is_month_end(datetime(2025, 1, 31)) is True

    def test_jan_30(self):
        assert _is_month_end(datetime(2025, 1, 30)) is False

    def test_feb_28_non_leap(self):
        assert _is_month_end(datetime(2025, 2, 28)) is True

    def test_feb_28_leap(self):
        assert _is_month_end(datetime(2024, 2, 28)) is False

    def test_feb_29_leap(self):
        assert _is_month_end(datetime(2024, 2, 29)) is True

    def test_apr_30(self):
        assert _is_month_end(datetime(2025, 4, 30)) is True


# ─── _format_amount ───────────────────────────────────────────────────────────


class TestFormatAmount:
    def test_positive(self):
        assert _format_amount(1234.56) == "1,234.56"

    def test_negative(self):
        assert _format_amount(-1234.56) == "-1,234.56"

    def test_zero(self):
        assert _format_amount(0.0) == "0.00"

    def test_large(self):
        assert _format_amount(1234567.89) == "1,234,567.89"

    def test_with_currency(self):
        assert _format_amount(100.0, "USD") == "USD100.00"

    def test_negative_with_currency(self):
        assert _format_amount(-100.0, "THB") == "-THB100.00"


# ─── _pad_line ────────────────────────────────────────────────────────────────


class TestPadLine:
    def test_basic(self):
        result = _pad_line("Revenue", "1,000.00")
        assert "Revenue" in result
        assert "1,000.00" in result
        assert len(result) == 72  # REPORT_WIDTH

    def test_with_prefix(self):
        result = _pad_line("Revenue", "1,000.00", "  ")
        assert result.startswith("  Revenue")
        assert result.endswith("1,000.00")

    def test_long_label(self):
        label = "A" * 60
        result = _pad_line(label, "100.00")
        assert label in result
        assert "100.00" in result


# ─── _truncate ────────────────────────────────────────────────────────────────


class TestTruncate:
    def test_under_limit(self):
        assert _truncate("short", 10) == "short"

    def test_at_limit(self):
        assert _truncate("exactly10!", 10) == "exactly10!"

    def test_over_limit(self):
        result = _truncate("this is too long", 10)
        assert len(result) == 10
        assert result.endswith("…")
        assert result == "this is t…"


# ─── _txn_to_dict ─────────────────────────────────────────────────────────────


class TestTxnToDict:
    def test_round_trip(self):
        txn = GLTransaction(
            date="2025-01-15",
            txn_type="Invoice",
            txn_id="5001",
            num="1001",
            customer="Acme Corp",
            memo="Test memo",
            account="Revenue",
            amount=5000.0,
        )
        d = _txn_to_dict(txn)
        assert d == {
            "date": "2025-01-15",
            "type": "Invoice",
            "id": "5001",
            "num": "1001",
            "customer": "Acme Corp",
            "memo": "Test memo",
            "account": "Revenue",
            "amount": 5000.0,
        }

    def test_empty_fields(self):
        txn = GLTransaction(amount=0.0)
        d = _txn_to_dict(txn)
        assert d["date"] == ""
        assert d["amount"] == 0.0


# ─── _collapse_tree ───────────────────────────────────────────────────────────


class TestCollapseTree:
    def test_children_removed(self):
        tree = {
            "name": "Revenue",
            "id": "100",
            "children": [
                {"name": "Consulting", "id": "101", "children": []},
                {"name": "Product", "id": "102", "children": []},
            ],
        }
        collapsed = _collapse_tree(tree)
        assert collapsed["children"] == []

    def test_name_id_preserved(self):
        tree = {"name": "Revenue", "id": "100", "children": []}
        collapsed = _collapse_tree(tree)
        assert collapsed["name"] == "Revenue"
        assert collapsed["id"] == "100"


# ─── _build_section_index ────────────────────────────────────────────────────


class TestBuildSectionIndex:
    def _make_sections(self):
        parent = GLSection("Revenue", "100")
        child = GLSection("Consulting", "101")
        parent.children = [child]
        return [parent]

    def test_name_lookup(self):
        idx = _build_section_index(self._make_sections())
        assert "Revenue" in idx
        assert idx["Revenue"].name == "Revenue"

    def test_id_lookup(self):
        idx = _build_section_index(self._make_sections())
        assert "100" in idx
        assert idx["100"].name == "Revenue"

    def test_nested_children_indexed(self):
        idx = _build_section_index(self._make_sections())
        assert "Consulting" in idx
        assert "101" in idx
        assert idx["101"].name == "Consulting"


# ─── _find_gl_section ────────────────────────────────────────────────────────


class TestFindGlSection:
    def _make_index(self):
        s1 = GLSection("Revenue", "100")
        s2 = GLSection("Consulting Revenue", "101")
        s1.children = [s2]
        return _build_section_index([s1])

    def test_exact_name_match(self):
        idx = self._make_index()
        result = _find_gl_section(idx, "Revenue")
        assert result is not None
        assert result.name == "Revenue"

    def test_id_preferred_over_name(self):
        idx = self._make_index()
        result = _find_gl_section(idx, "Revenue", "100")
        assert result.id == "100"

    def test_suffix_fallback(self):
        idx = self._make_index()
        result = _find_gl_section(idx, "Revenue", "")
        assert result is not None
        # "Revenue" is an exact match, should find it
        assert result.name == "Revenue"

    def test_miss_returns_none(self):
        idx = self._make_index()
        result = _find_gl_section(idx, "Nonexistent", "999")
        assert result is None

    def test_suffix_match(self):
        idx = self._make_index()
        s3 = GLSection("Other Consulting", "103")
        idx["Other Consulting"] = s3
        result = _find_gl_section(idx, "Consulting", "")
        assert result is not None
        assert result.name == "Other Consulting"
