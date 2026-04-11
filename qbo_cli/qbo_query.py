"""QBO query string helpers."""

from __future__ import annotations


def _qbo_escape(value: str) -> str:
    """Escape a value for use in QBO query strings.
    Doubles single quotes for string literals; strips % to prevent
    unintended LIKE wildcard expansion."""
    return value.replace("'", "''").replace("%", "")
