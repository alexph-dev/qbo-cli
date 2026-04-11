"""Error reporting helpers: die() for fatal errors, err_print() for stderr."""

from __future__ import annotations

import sys
from typing import NoReturn


def die(msg: str, code: int = 1) -> NoReturn:
    """Print to stderr and exit."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


def err_print(msg: str) -> None:
    print(msg, file=sys.stderr)
