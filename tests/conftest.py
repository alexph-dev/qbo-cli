"""Shared fixtures for qbo-cli tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from qbo_cli.cli import Config, QBOClient, TokenManager

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def gl_fixture():
    """Loaded GL report JSON fixture."""
    return json.loads((FIXTURES_DIR / "gl_report_nested.json").read_text())


@pytest.fixture
def customers_fixture():
    """Loaded customer query JSON fixture."""
    return json.loads((FIXTURES_DIR / "query_customers.json").read_text())


@pytest.fixture
def fake_config():
    """Config object without disk IO."""
    cfg = Config.__new__(Config)
    cfg.client_id = "test-client-id"
    cfg.client_secret = "test-client-secret"
    cfg.redirect_uri = "http://localhost:8844/callback"
    cfg.realm_id = "1234567890"
    cfg.sandbox = False
    return cfg


@pytest.fixture
def fake_token_mgr(fake_config):
    """TokenManager with mocked get_valid_token."""
    mgr = TokenManager.__new__(TokenManager)
    mgr.config = fake_config
    mgr._tokens = {
        "access_token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "expires_at": 9999999999,
        "refresh_expires_at": 9999999999,
        "realm_id": "1234567890",
    }
    mgr.get_valid_token = MagicMock(return_value="fake-access-token")
    mgr.load = MagicMock(return_value=mgr._tokens)
    return mgr


@pytest.fixture
def mock_client(fake_config, fake_token_mgr):
    """QBOClient with mocked request method."""
    client = QBOClient(fake_config, fake_token_mgr)
    client.request = MagicMock()
    return client


def make_args(**overrides) -> argparse.Namespace:
    """Factory for argparse.Namespace with sensible defaults."""
    defaults = {
        "command": "query",
        "format": "text",
        "sandbox": False,
        "output": None,
        "sql": "SELECT * FROM Customer",
        "max_pages": 100,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)
