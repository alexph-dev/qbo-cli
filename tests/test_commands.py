"""Tests for cmd_* command handlers (end-to-end with mocked client)."""

from __future__ import annotations

from contextlib import ExitStack
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from qbo_cli.cli import (
    QBOClient,
    _resolve_fmt,
    cmd_create,
    cmd_gl_report,
    cmd_query,
    cmd_report,
    cmd_search,
    cmd_update,
    main,
)
from tests.conftest import make_args

# ─── cmd_query ────────────────────────────────────────────────────────────────


class TestCmdQuery:
    def test_query_forwards_sql_and_max_pages(self, fake_config, fake_token_mgr):
        """Verify cmd_query passes SQL and max_pages to client.query."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"QueryResponse": {"Customer": [{"Id": "1", "DisplayName": "Acme"}]}})
        args = make_args(command="query", sql="SELECT Id FROM Customer", output=None, format="text", max_pages=50)

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_query(args, fake_config, fake_token_mgr)

        # The query method calls request internally — verify the SQL was forwarded
        call_args = client.request.call_args
        query_param = call_args[1]["params"]["query"] if "params" in call_args[1] else call_args[0][2]["query"]
        assert "SELECT Id FROM Customer" in query_param

    def test_query_json_output(self, fake_config, fake_token_mgr, capsys):
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"QueryResponse": {"Customer": [{"Id": "1", "DisplayName": "Acme"}]}})
        args = make_args(command="query", sql="SELECT * FROM Customer", output="json", format="text")

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_query(args, fake_config, fake_token_mgr)

        captured = capsys.readouterr().out
        data = json.loads(captured)
        assert data[0]["DisplayName"] == "Acme"

    def test_query_text_output(self, fake_config, fake_token_mgr, capsys):
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"QueryResponse": {"Customer": [{"Id": "1", "DisplayName": "Acme"}]}})
        args = make_args(command="query", sql="SELECT * FROM Customer", output=None, format="text")

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_query(args, fake_config, fake_token_mgr)

        captured = capsys.readouterr().out
        assert "Acme" in captured
        assert "(1 rows)" in captured


# ─── cmd_search ───────────────────────────────────────────────────────────────


class TestCmdSearch:
    def test_search_filters_nested_json_case_insensitive(self, fake_config, fake_token_mgr, capsys):
        client = QBOClient(fake_config, fake_token_mgr)
        client.query = MagicMock(
            return_value=[
                {"Id": "1", "PrivateNote": "Owner Memo", "Line": [{"Description": "Move-in fee"}]},
                {"Id": "2", "PrivateNote": "Misc", "Line": [{"Description": "Monthly Service"}]},
            ]
        )
        args = make_args(
            command="search",
            sql="SELECT * FROM Invoice",
            text="monthly service",
            case_sensitive=False,
            max_pages=7,
            output="json",
            format="text",
        )

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_search(args, fake_config, fake_token_mgr)

        client.query.assert_called_once_with("SELECT * FROM Invoice", max_pages=7)
        data = json.loads(capsys.readouterr().out)
        assert [row["Id"] for row in data] == ["2"]

    def test_search_case_sensitive_flag(self, fake_config, fake_token_mgr, capsys):
        client = QBOClient(fake_config, fake_token_mgr)
        client.query = MagicMock(return_value=[{"Id": "1", "PrivateNote": "Owner Memo"}])
        args = make_args(
            command="search",
            sql="SELECT * FROM Invoice",
            text="owner memo",
            case_sensitive=True,
            max_pages=100,
            output="json",
            format="text",
        )

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_search(args, fake_config, fake_token_mgr)

        data = json.loads(capsys.readouterr().out)
        assert data == []


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


# ─── cmd_gl_report ────────────────────────────────────────────────────────────


class TestCmdGlReport:
    @staticmethod
    def _run_gl_report_json(
        fake_config,
        fake_token_mgr,
        capsys,
        *,
        output=None,
        format="text",
        customer=None,
    ):
        client = MagicMock()
        client.report = MagicMock(return_value={"Header": {"Option": []}, "Rows": {}})
        args = make_args(
            command="gl-report",
            customer=customer,
            account="125",
            start="2026-02-01",
            end="2026-02-28",
            method="Cash",
            currency="THB",
            list_accounts=False,
            output=output,
            format=format,
            no_sub=False,
            by_customer=False,
            sort="alpha",
        )

        with ExitStack() as stack:
            stack.enter_context(patch("qbo_cli.cli.QBOClient", return_value=client))
            if customer is not None:
                stack.enter_context(patch("qbo_cli.cli._resolve_customer", return_value=("104", "PM:R-CB1")))
            stack.enter_context(
                patch(
                    "qbo_cli.cli._discover_account_tree",
                    return_value={"name": "PM Owner Funds", "id": "125", "children": []},
                )
            )
            stack.enter_context(patch("qbo_cli.cli._parse_gl_rows", return_value=[]))
            stack.enter_context(patch("qbo_cli.cli._build_section_index", return_value={}))
            stack.enter_context(patch("qbo_cli.cli._extract_dates_from_gl", return_value=(None, None)))
            stack.enter_context(patch("qbo_cli.cli._compute_subtotal", return_value=(123.45, 0)))
            stack.enter_context(patch("qbo_cli.cli._find_gl_section", return_value=None))
            cmd_gl_report(args, fake_config, fake_token_mgr)

        return json.loads(capsys.readouterr().out)

    def test_gl_report_json_output(self, fake_config, fake_token_mgr, capsys):
        data = self._run_gl_report_json(
            fake_config,
            fake_token_mgr,
            capsys,
            output="json",
            customer="R-CB1",
        )
        assert data["customer"] == "PM:R-CB1"
        assert data["account"]["name"] == "PM Owner Funds"
        assert data["total"] == pytest.approx(123.45)

    def test_gl_list_accounts_json_output_for_tree(self, fake_config, fake_token_mgr, capsys):
        client = MagicMock()
        args = make_args(
            command="gl-report",
            customer=None,
            account="125",
            list_accounts=True,
            output="json",
            format="text",
        )

        with (
            patch("qbo_cli.cli.QBOClient", return_value=client),
            patch(
                "qbo_cli.cli._discover_account_tree",
                return_value={"name": "PM Owner Funds", "id": "125", "children": []},
            ),
        ):
            cmd_gl_report(args, fake_config, fake_token_mgr)

        data = json.loads(capsys.readouterr().out)
        assert data == {"name": "PM Owner Funds", "id": "125", "children": []}

    def test_gl_list_accounts_json_output_for_top_level(self, fake_config, fake_token_mgr, capsys):
        client = MagicMock()
        args = make_args(
            command="gl-report",
            customer=None,
            account=None,
            list_accounts=True,
            output=None,
            format="json",
        )

        with (
            patch("qbo_cli.cli.QBOClient", return_value=client),
            patch(
                "qbo_cli.cli._list_all_accounts_data",
                return_value={
                    "groups": [
                        {"type": "Income", "accounts": [{"id": "125", "name": "Revenue", "sub_account_count": 2}]}
                    ],
                    "top_level_count": 1,
                    "total_count": 3,
                },
            ),
        ):
            cmd_gl_report(args, fake_config, fake_token_mgr)

        data = json.loads(capsys.readouterr().out)
        assert data["top_level_count"] == 1
        assert data["groups"][0]["accounts"][0]["sub_account_count"] == 2

    def test_gl_report_respects_global_format_flag(self, fake_config, fake_token_mgr, capsys):
        data = self._run_gl_report_json(
            fake_config,
            fake_token_mgr,
            capsys,
            output=None,
            format="json",
        )
        assert data["account"]["name"] == "PM Owner Funds"
        assert data["total"] == pytest.approx(123.45)


# ─── cmd_create / cmd_update ──────────────────────────────────────────────────


class TestCmdCreateUpdate:
    def test_cmd_create_calls_post_with_entity_and_body(self, fake_config, fake_token_mgr):
        """Verify create calls client.request(POST, entity, body)."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"Customer": {"Id": "99", "DisplayName": "New Corp"}})
        args = make_args(command="create", entity="Customer", output="json", format="text")

        body = {"DisplayName": "New Corp"}
        with (
            patch("qbo_cli.cli.QBOClient", return_value=client),
            patch("qbo_cli.cli._read_stdin_json", return_value=body),
        ):
            cmd_create(args, fake_config, fake_token_mgr)

        # Verify the actual API call
        client.request.assert_called_once_with("POST", "customer", json_body=body)

    def test_cmd_update_calls_post_with_entity_and_body(self, fake_config, fake_token_mgr):
        """Verify update calls client.request(POST, entity, body)."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"Customer": {"Id": "1", "DisplayName": "Updated Corp"}})
        args = make_args(command="update", entity="Customer", output="json", format="text")

        body = {"Id": "1", "DisplayName": "Updated Corp", "SyncToken": "0"}
        with (
            patch("qbo_cli.cli.QBOClient", return_value=client),
            patch("qbo_cli.cli._read_stdin_json", return_value=body),
        ):
            cmd_update(args, fake_config, fake_token_mgr)

        client.request.assert_called_once_with("POST", "customer", json_body=body)

    def test_cmd_create_json_output(self, fake_config, fake_token_mgr, capsys):
        """Verify create outputs JSON when -o json."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"Customer": {"Id": "99", "DisplayName": "New Corp"}})
        args = make_args(command="create", entity="Customer", output="json", format="text")

        with (
            patch("qbo_cli.cli.QBOClient", return_value=client),
            patch("qbo_cli.cli._read_stdin_json", return_value={"DisplayName": "New Corp"}),
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


# ─── main parser: subcommand --format alias ──────────────────────────────────


class TestSubcommandFormatAlias:
    @pytest.mark.parametrize(
        ("argv", "handler_name"),
        [
            (["qbo", "query", "SELECT Id FROM Customer", "--format", "json"], "cmd_query"),
            (["qbo", "get", "Customer", "1", "--format", "json"], "cmd_get"),
            (["qbo", "create", "Customer", "--format", "json"], "cmd_create"),
            (["qbo", "update", "Customer", "--format", "json"], "cmd_update"),
            (["qbo", "delete", "Customer", "1", "--format", "json"], "cmd_delete"),
            (["qbo", "report", "ProfitAndLoss", "--format", "json"], "cmd_report"),
            (["qbo", "raw", "GET", "companyinfo/1", "--format", "json"], "cmd_raw"),
            (["qbo", "gl-report", "-a", "125", "--format", "json"], "cmd_gl_report"),
        ],
    )
    def test_format_alias_after_subcommand_maps_to_output(self, argv, handler_name):
        fake_config = MagicMock()
        fake_config.validate = MagicMock()
        fake_config.sandbox = False
        fake_token_mgr = MagicMock()
        captured = {}

        def _capture(args, config, token_mgr):
            captured["args"] = args
            captured["config"] = config
            captured["token_mgr"] = token_mgr

        with (
            patch("qbo_cli.cli.Config", return_value=fake_config),
            patch("qbo_cli.cli.TokenManager", return_value=fake_token_mgr),
            patch(f"qbo_cli.cli.{handler_name}", side_effect=_capture) as mock_handler,
            patch.object(sys, "argv", argv),
        ):
            main()

        mock_handler.assert_called_once()
        fake_config.validate.assert_called_once()
        assert captured["args"].output == "json"
