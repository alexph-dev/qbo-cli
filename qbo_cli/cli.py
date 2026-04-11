#!/usr/bin/env python3
"""qbo-cli — Command-line interface for QuickBooks Online API.

Thin wiring layer: argument parsing, profile resolution, runtime assembly,
and command dispatch. All feature code lives in sibling modules.

Homepage: https://github.com/alexph-dev/qbo-cli
License: MIT
"""

from __future__ import annotations

import argparse
import os
import sys

from qbo_cli.auth import (
    TokenManager,
    cmd_auth_init,
    cmd_auth_refresh,
    cmd_auth_setup,
    cmd_auth_status,
)
from qbo_cli.commands import (
    cmd_create,
    cmd_delete,
    cmd_get,
    cmd_query,
    cmd_raw,
    cmd_report,
    cmd_search,
    cmd_update,
    cmd_void,
)
from qbo_cli.config import Config
from qbo_cli.errors import die
from qbo_cli.gl_report import cmd_gl_report
from qbo_cli.parser import _build_parser


def _resolve_profile(args) -> str:
    """Resolve profile name from CLI flags, env var, or default."""
    if args.profile:
        return args.profile
    if args.sandbox:
        return "dev"
    return os.environ.get("QBO_PROFILE", "prod")


def _build_runtime(args) -> tuple[Config, TokenManager]:
    """Create runtime config and token manager for parsed args."""
    profile = _resolve_profile(args)
    config = Config(profile=profile)
    if args.sandbox and not args.profile:
        config.sandbox = True
    return config, TokenManager(config)


def _dispatch_command(args, auth_parser: argparse.ArgumentParser, config: Config, token_mgr: TokenManager) -> None:
    """Dispatch parsed CLI args to the appropriate handler."""
    if args.command == "auth":
        if not args.auth_command:
            auth_parser.print_help()
            sys.exit(1)

        auth_dispatch = {
            "init": cmd_auth_init,
            "status": cmd_auth_status,
            "refresh": cmd_auth_refresh,
            "setup": cmd_auth_setup,
        }
        auth_dispatch[args.auth_command](args, config, token_mgr)
        return

    dispatch = {
        "query": cmd_query,
        "search": cmd_search,
        "get": cmd_get,
        "create": cmd_create,
        "update": cmd_update,
        "delete": cmd_delete,
        "void": cmd_void,
        "report": cmd_report,
        "raw": cmd_raw,
        "gl-report": cmd_gl_report,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        die(f"Unknown command '{args.command}'")

    config.validate()
    handler(args, config, token_mgr)


def main() -> None:
    parser, auth_parser = _build_parser()

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config, token_mgr = _build_runtime(args)
    _dispatch_command(args, auth_parser, config, token_mgr)


if __name__ == "__main__":
    main()
