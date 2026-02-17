"""Tests for cmd_* command handlers (end-to-end with mocked client)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from qbo_cli.cli import (
    QBOClient,
    cmd_create,
    cmd_query,
    cmd_report,
    cmd_update,
    _resolve_fmt,
)
from tests.conftest import make_args


# ─── cmd_query ────────────────────────────────────────────────────────────────


class TestCmdQuery:
    def test_query_forwards_sql_and_max_pages(self, fake_config, fake_token_mgr):
        """Verify cmd_query passes SQL and max_pages to client.query."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(
            return_value={"QueryResponse": {"Customer": [{"Id": "1", "DisplayName": "Acme"}]}}
        )
        args = make_args(command="query", sql="SELECT Id FROM Customer", output=None, format="text", max_pages=50)

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_query(args, fake_config, fake_token_mgr)

        # The query method calls request internally — verify the SQL was forwarded
        call_args = client.request.call_args
        query_param = call_args[1]["params"]["query"] if "params" in call_args[1] else call_args[0][2]["query"]
        assert "SELECT Id FROM Customer" in query_param

    def test_query_json_output(self, fake_config, fake_token_mgr, capsys):
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(
            return_value={"QueryResponse": {"Customer": [{"Id": "1", "DisplayName": "Acme"}]}}
        )
        args = make_args(command="query", sql="SELECT * FROM Customer", output="json", format="text")

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_query(args, fake_config, fake_token_mgr)

        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data[0]["DisplayName"] == "Acme"

    def test_query_text_output(self, fake_config, fake_token_mgr, capsys):
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(
            return_value={"QueryResponse": {"Customer": [{"Id": "1", "DisplayName": "Acme"}]}}
        )
        args = make_args(command="query", sql="SELECT * FROM Customer", output=None, format="text")

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_query(args, fake_config, fake_token_mgr)

        captured = capsys.readouterr().out
        assert "Acme" in captured
        assert "(1 rows)" in captured


# ─── cmd_report ───────────────────────────────────────────────────────────────


class TestCmdReport:
    def test_report_basic(self, fake_config, fake_token_mgr, capsys):
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"Header": {"ReportName": "ProfitAndLoss"}, "Rows": {}})
        args = make_args(
            command="report",
            report_type="ProfitAndLoss",
            start_date="2025-01-01",
            end_date="2025-12-31",
            date_macro=None,
            params=[],
            output="json",
            format="text",
        )

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_report(args, fake_config, fake_token_mgr)

        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data["Header"]["ReportName"] == "ProfitAndLoss"

    def test_report_forwards_params(self, fake_config, fake_token_mgr, capsys):
        """Verify date_macro and extra key=value params are forwarded to the API."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"Header": {}, "Rows": {}})
        args = make_args(
            command="report",
            report_type="BalanceSheet",
            start_date=None,
            end_date=None,
            date_macro="Last Year",
            params=["accounting_method=Cash"],
            output="json",
            format="text",
        )

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_report(args, fake_config, fake_token_mgr)

        # client.request is called by client.report() internally
        call_kwargs = client.request.call_args[1]
        params = call_kwargs.get("params", {})
        assert params["date_macro"] == "Last Year"
        assert params["accounting_method"] == "Cash"


# ─── cmd_create / cmd_update ──────────────────────────────────────────────────


class TestCmdCreateUpdate:
    def test_cmd_create_calls_post_with_entity_and_body(self, fake_config, fake_token_mgr):
        """Verify create calls client.request(POST, entity, body)."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"Customer": {"Id": "99", "DisplayName": "New Corp"}})
        args = make_args(command="create", entity="Customer", output="json", format="text")

        body = {"DisplayName": "New Corp"}
        with patch("qbo_cli.cli.QBOClient", return_value=client), patch(
            "qbo_cli.cli._read_stdin_json", return_value=body
        ):
            cmd_create(args, fake_config, fake_token_mgr)

        # Verify the actual API call
        client.request.assert_called_once_with("POST", "customer", json_body=body)

    def test_cmd_update_calls_post_with_entity_and_body(self, fake_config, fake_token_mgr):
        """Verify update calls client.request(POST, entity, body)."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(
            return_value={"Customer": {"Id": "1", "DisplayName": "Updated Corp"}}
        )
        args = make_args(command="update", entity="Customer", output="json", format="text")

        body = {"Id": "1", "DisplayName": "Updated Corp", "SyncToken": "0"}
        with patch("qbo_cli.cli.QBOClient", return_value=client), patch(
            "qbo_cli.cli._read_stdin_json", return_value=body
        ):
            cmd_update(args, fake_config, fake_token_mgr)

        client.request.assert_called_once_with("POST", "customer", json_body=body)

    def test_cmd_create_json_output(self, fake_config, fake_token_mgr, capsys):
        """Verify create outputs JSON when -o json."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"Customer": {"Id": "99", "DisplayName": "New Corp"}})
        args = make_args(command="create", entity="Customer", output="json", format="text")

        with patch("qbo_cli.cli.QBOClient", return_value=client), patch(
            "qbo_cli.cli._read_stdin_json", return_value={"DisplayName": "New Corp"}
        ):
            cmd_create(args, fake_config, fake_token_mgr)

        data = json.loads(capsys.readouterr().out)
        assert data["Customer"]["Id"] == "99"


# ─── _resolve_fmt ─────────────────────────────────────────────────────────────


class TestResolveFmt:
    def test_output_overrides_format(self):
        args = make_args(output="json", format="text")
        assert _resolve_fmt(args) == "json"

    def test_format_fallback_when_output_none(self):
        args = make_args(output=None, format="tsv")
        assert _resolve_fmt(args) == "tsv"

    def test_format_fallback_when_no_output_attr(self):
        from argparse import Namespace

        args = Namespace(format="text")
        assert _resolve_fmt(args) == "text"
