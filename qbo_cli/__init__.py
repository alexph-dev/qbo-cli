"""qbo-cli — QuickBooks Online command-line interface.

Version string is resolved from installed package metadata so that
`pyproject.toml` stays the single source of truth. For uninstalled
source checkouts, fall back to parsing `pyproject.toml` directly so
`qbo --version` still reports the right value from a clean `git clone`.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path


def _version_from_pyproject() -> str | None:
    """Read version from pyproject.toml for uninstalled source checkouts."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        text = pyproject.read_text()
    except OSError:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


try:
    __version__: str = _pkg_version("qbo-cli")
except PackageNotFoundError:  # pragma: no cover - uninstalled source checkout
    __version__ = _version_from_pyproject() or "0.0.0+unknown"

__all__ = ["__version__"]
