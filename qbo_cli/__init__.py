"""qbo-cli — QuickBooks Online command-line interface.

Version string is resolved from installed package metadata so that
`pyproject.toml` stays the single source of truth. Fallback preserves
behavior for editable checkouts that have not yet been installed.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__: str = _pkg_version("qbo-cli")
except PackageNotFoundError:  # pragma: no cover - uninstalled source checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
