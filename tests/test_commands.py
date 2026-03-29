"""Tests for cmd_* command handlers (end-to-end with mocked client)."""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from qbo_cli.cli import (
    _REPORT_ALIAS_MAP,
    REPORT_REGISTRY,
    QBOClient,
    _format_report_list,
    _resolve_fmt,
    _resolve_profile,
    _resolve_report_name,
    cmd_create,
    cmd_gl_report,
    cmd_query,
    cmd_report,
    cmd_search,
    cmd_update,
    cmd_void,
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
            list_reports=False,
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
            list_reports=False,
        )

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_report(args, fake_config, fake_token_mgr)

        # client.request is called by client.report() internally
        call_kwargs = client.request.call_args[1]
        params = call_kwargs.get("params", {})
        assert params["date_macro"] == "Last Year"
        assert params["accounting_method"] == "Cash"


# ─── report aliases and --list ────────────────────────────────────────────────


class TestReportAliases:
    def test_canonical_name_resolves_to_itself(self):
        assert _resolve_report_name("ProfitAndLoss") == "ProfitAndLoss"

    def test_short_alias_resolves(self):
        assert _resolve_report_name("PnL") == "ProfitAndLoss"
        assert _resolve_report_name("GL") == "GeneralLedger"
        assert _resolve_report_name("BS") == "BalanceSheet"
        assert _resolve_report_name("CF") == "CashFlow"
        assert _resolve_report_name("TB") == "TrialBalance"
        assert _resolve_report_name("AR") == "AgedReceivables"
        assert _resolve_report_name("AP") == "AgedPayables"

    def test_case_insensitive_resolution(self, capsys):
        assert _resolve_report_name("pnl") == "ProfitAndLoss"
        assert _resolve_report_name("gl") == "GeneralLedger"
        assert _resolve_report_name("profitandloss") == "ProfitAndLoss"
        assert _resolve_report_name("BALANCESHEET") == "BalanceSheet"

    def test_unknown_name_passes_through_with_warning(self, capsys):
        result = _resolve_report_name("CustomReport")
        assert result == "CustomReport"
        stderr = capsys.readouterr().err
        assert "not a known report type" in stderr
        assert "qbo report --list" in stderr

    def test_all_registry_entries_in_alias_map(self):
        for canonical in REPORT_REGISTRY:
            assert canonical.lower() in _REPORT_ALIAS_MAP
            assert _REPORT_ALIAS_MAP[canonical.lower()] == canonical

    def test_all_aliases_in_alias_map(self):
        for canonical, (_desc, aliases) in REPORT_REGISTRY.items():
            for alias in aliases:
                assert alias.lower() in _REPORT_ALIAS_MAP
                assert _REPORT_ALIAS_MAP[alias.lower()] == canonical


class TestCmdReportList:
    def test_list_reports_prints_table(self, fake_config, fake_token_mgr, capsys):
        args = make_args(
            command="report",
            report_type=None,
            list_reports=True,
            start_date=None,
            end_date=None,
            date_macro=None,
            params=[],
            output="text",
            format="text",
        )
        cmd_report(args, fake_config, fake_token_mgr)
        out = capsys.readouterr().out
        assert "Available reports:" in out
        assert "ProfitAndLoss" in out
        assert "GeneralLedger" in out
        assert "(GL)" in out
        assert "(PnL, P&L)" in out

    def test_missing_report_type_shows_error_and_list(self, fake_config, fake_token_mgr):
        args = make_args(
            command="report",
            report_type=None,
            list_reports=False,
            start_date=None,
            end_date=None,
            date_macro=None,
            params=[],
            output="text",
            format="text",
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_report(args, fake_config, fake_token_mgr)
        assert exc_info.value.code == 1

    def test_alias_resolves_before_api_call(self, fake_config, fake_token_mgr, capsys):
        """Verify alias is resolved to canonical name before calling client.report."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(return_value={"Header": {"ReportName": "GeneralLedger"}, "Rows": {}})
        args = make_args(
            command="report",
            report_type="GL",
            start_date=None,
            end_date=None,
            date_macro=None,
            params=[],
            output="json",
            format="text",
            list_reports=False,
        )
        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_report(args, fake_config, fake_token_mgr)
        call_args = client.request.call_args
        assert "reports/GeneralLedger" in call_args[0][1]

    def test_format_report_list_includes_all_entries(self):
        output = _format_report_list()
        for canonical in REPORT_REGISTRY:
            assert canonical in output

    def test_list_flag_takes_precedence_over_report_type(self, fake_config, fake_token_mgr, capsys):
        """--list prints report table and exits even when report_type is given."""
        args = make_args(
            command="report",
            report_type="PnL",
            list_reports=True,
            start_date=None,
            end_date=None,
            date_macro=None,
            params=[],
            output="text",
            format="text",
        )
        cmd_report(args, fake_config, fake_token_mgr)
        out = capsys.readouterr().out
        assert "Available reports:" in out


class TestReportArgparse:
    def test_report_list_flag_parsed(self):
        """Verify --list flag is parsed by argparse."""
        with patch("qbo_cli.cli.cmd_report") as mock_cmd, patch.object(sys, "argv", ["qbo", "report", "--list"]):
            mock_cmd.return_value = None
            try:
                main()
            except SystemExit:
                pass
            if mock_cmd.called:
                args = mock_cmd.call_args[0][0]
                assert args.list_reports is True

    def test_report_alias_parsed_as_report_type(self):
        """Verify alias is captured as report_type positional arg."""
        with (
            patch("qbo_cli.cli.cmd_report") as mock_cmd,
            patch.object(sys, "argv", ["qbo", "report", "PnL", "-o", "json"]),
        ):
            mock_cmd.return_value = None
            try:
                main()
            except SystemExit:
                pass
            if mock_cmd.called:
                args = mock_cmd.call_args[0][0]
                assert args.report_type == "PnL"


# ─── cmd_gl_report ────────────────────────────────────────────────────────────


class TestCmdGlReport:
    @staticmethod
    def _make_gl_args(**overrides):
        defaults = {
            "command": "gl-report",
            "customer": None,
            "account": "125",
            "start": "2026-02-01",
            "end": "2026-02-28",
            "method": "Cash",
            "currency": "THB",
            "list_accounts": False,
            "output": None,
            "format": "text",
            "no_sub": False,
            "by_customer": False,
            "sort": "alpha",
        }
        defaults.update(overrides)
        return make_args(**defaults)

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
        args = TestCmdGlReport._make_gl_args(
            customer=customer,
            output=output,
            format=format,
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

    @staticmethod
    def _run_gl_list_accounts_tree(
        fake_config,
        fake_token_mgr,
        capsys,
        *,
        output=None,
        format="text",
    ):
        client = MagicMock()
        args = TestCmdGlReport._make_gl_args(
            account="125",
            list_accounts=True,
            output=output,
            format=format,
        )

        with (
            patch("qbo_cli.cli.QBOClient", return_value=client),
            patch(
                "qbo_cli.cli._discover_account_tree",
                return_value={"name": "PM Owner Funds", "id": "125", "children": []},
            ),
        ):
            cmd_gl_report(args, fake_config, fake_token_mgr)

        return json.loads(capsys.readouterr().out)

    @staticmethod
    def _run_gl_list_accounts_top_level(
        fake_config,
        fake_token_mgr,
        capsys,
        *,
        output=None,
        format="text",
    ):
        client = MagicMock()
        args = TestCmdGlReport._make_gl_args(
            account=None,
            list_accounts=True,
            output=output,
            format=format,
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
        data = self._run_gl_list_accounts_tree(
            fake_config,
            fake_token_mgr,
            capsys,
            output="json",
            format="text",
        )
        assert data == {"name": "PM Owner Funds", "id": "125", "children": []}

    def test_gl_list_accounts_tree_respects_global_format_flag(self, fake_config, fake_token_mgr, capsys):
        data = self._run_gl_list_accounts_tree(
            fake_config,
            fake_token_mgr,
            capsys,
            output=None,
            format="json",
        )
        assert data == {"name": "PM Owner Funds", "id": "125", "children": []}

    def test_gl_list_accounts_json_output_for_top_level(self, fake_config, fake_token_mgr, capsys):
        data = self._run_gl_list_accounts_top_level(
            fake_config,
            fake_token_mgr,
            capsys,
            output=None,
            format="json",
        )
        assert data["top_level_count"] == 1
        assert data["groups"][0]["accounts"][0]["sub_account_count"] == 2

    @pytest.mark.parametrize("fmt", ["txns", "expanded"])
    def test_gl_list_accounts_rejects_unsupported_formats(self, fake_config, fake_token_mgr, capsys, fmt):
        args = self._make_gl_args(account="125", list_accounts=True, output=fmt)
        with (
            patch("qbo_cli.cli.QBOClient", return_value=MagicMock()),
            pytest.raises(SystemExit),
        ):
            cmd_gl_report(args, fake_config, fake_token_mgr)

        assert "supports text or json output only" in capsys.readouterr().err

    def test_gl_report_rejects_global_tsv_flag(self, fake_config, fake_token_mgr, capsys):
        args = self._make_gl_args(output=None, format="tsv")
        with (
            patch("qbo_cli.cli.QBOClient", return_value=MagicMock()),
            patch(
                "qbo_cli.cli._discover_account_tree",
                return_value={"name": "PM Owner Funds", "id": "125", "children": []},
            ),
            patch("qbo_cli.cli._parse_gl_rows", return_value=[]),
            patch("qbo_cli.cli._build_section_index", return_value={}),
            patch("qbo_cli.cli._extract_dates_from_gl", return_value=(None, None)),
            pytest.raises(SystemExit),
        ):
            cmd_gl_report(args, fake_config, fake_token_mgr)

        assert "gl-report does not support tsv output" in capsys.readouterr().err

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


# ─── cmd_void ────────────────────────────────────────────────────────────────


class TestCmdVoid:
    def test_cmd_void_calls_client_void(self, fake_config, fake_token_mgr, capsys):
        """Verify cmd_void calls client.void with entity and ID, emits result."""
        client = QBOClient(fake_config, fake_token_mgr)
        client.request = MagicMock(
            side_effect=[
                {"Invoice": {"Id": "55", "SyncToken": "1", "TotalAmt": 100}},
                {"Invoice": {"Id": "55", "SyncToken": "2", "TotalAmt": 0}},
            ]
        )
        args = make_args(command="void", entity="Invoice", id="55", output="json", format="text")

        with patch("qbo_cli.cli.QBOClient", return_value=client):
            cmd_void(args, fake_config, fake_token_mgr)

        assert client.request.call_count == 2
        out = json.loads(capsys.readouterr().out)
        assert out["Invoice"]["Id"] == "55"


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
            (["qbo", "void", "Invoice", "1", "--format", "json"], "cmd_void"),
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


class TestMainGlobalFormat:
    def test_global_format_before_gl_report_reaches_handler(self):
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
            patch("qbo_cli.cli.cmd_gl_report", side_effect=_capture) as mock_handler,
            patch.object(sys, "argv", ["qbo", "-f", "json", "gl-report", "-a", "125"]),
        ):
            main()

        mock_handler.assert_called_once()
        fake_config.validate.assert_called_once()
        assert captured["args"].format == "json"
        assert captured["args"].output is None


# ─── Profile resolution ──────────────────────────────────────────────────────


class TestResolveProfile:
    def test_profile_flag(self):
        args = make_args(profile="dev", sandbox=False)
        assert _resolve_profile(args) == "dev"

    def test_sandbox_flag(self):
        args = make_args(profile=None, sandbox=True)
        assert _resolve_profile(args) == "dev"

    def test_default_is_prod(self):
        args = make_args(profile=None, sandbox=False)
        with patch.dict("os.environ", {}, clear=False):
            import os

            old = os.environ.pop("QBO_PROFILE", None)
            try:
                assert _resolve_profile(args) == "prod"
            finally:
                if old is not None:
                    os.environ["QBO_PROFILE"] = old

    def test_env_var_fallback(self):
        args = make_args(profile=None, sandbox=False)
        with patch.dict("os.environ", {"QBO_PROFILE": "staging"}, clear=False):
            assert _resolve_profile(args) == "staging"

    def test_profile_flag_wins_over_sandbox(self):
        args = make_args(profile="custom", sandbox=True)
        assert _resolve_profile(args) == "custom"

    def test_profile_flag_wins_over_env_var(self):
        args = make_args(profile="custom", sandbox=False)
        with patch.dict("os.environ", {"QBO_PROFILE": "other"}, clear=False):
            assert _resolve_profile(args) == "custom"

    def test_arbitrary_profile_name(self):
        args = make_args(profile="my-company_1", sandbox=False)
        assert _resolve_profile(args) == "my-company_1"


# ─── auth setup (profiled config) ────────────────────────────────────────────


class TestCmdAuthSetup:
    def test_setup_writes_prod_profile(self, tmp_path, fake_config, fake_token_mgr):
        from qbo_cli.cli import cmd_auth_setup

        config_file = tmp_path / "config.json"
        fake_config.profile = "prod"
        args = make_args(command="auth", auth_command="setup")
        with (
            patch("qbo_cli.cli.CONFIG_PATH", config_file),
            patch("qbo_cli.cli.QBO_DIR", tmp_path),
            patch("builtins.input", side_effect=["new-id", "new-secret", ""]),
        ):
            cmd_auth_setup(args, fake_config, fake_token_mgr)
        data = json.loads(config_file.read_text())
        assert "prod" in data
        assert data["prod"]["client_id"] == "new-id"
        assert data["prod"]["client_secret"] == "new-secret"

    def test_setup_writes_dev_profile_preserves_prod(self, tmp_path, fake_config, fake_token_mgr):
        from qbo_cli.cli import cmd_auth_setup

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"prod": {"client_id": "prod-id", "client_secret": "prod-secret"}}))
        fake_config.profile = "dev"
        args = make_args(command="auth", auth_command="setup")
        with (
            patch("qbo_cli.cli.CONFIG_PATH", config_file),
            patch("qbo_cli.cli.QBO_DIR", tmp_path),
            patch("builtins.input", side_effect=["dev-id", "dev-secret", ""]),
        ):
            cmd_auth_setup(args, fake_config, fake_token_mgr)
        data = json.loads(config_file.read_text())
        assert data["prod"]["client_id"] == "prod-id"
        assert data["dev"]["client_id"] == "dev-id"

    def test_setup_on_empty_config(self, tmp_path, fake_config, fake_token_mgr):
        from qbo_cli.cli import cmd_auth_setup

        config_file = tmp_path / "config.json"
        fake_config.profile = "prod"
        args = make_args(command="auth", auth_command="setup")
        with (
            patch("qbo_cli.cli.CONFIG_PATH", config_file),
            patch("qbo_cli.cli.QBO_DIR", tmp_path),
            patch("builtins.input", side_effect=["x", "y", ""]),
        ):
            cmd_auth_setup(args, fake_config, fake_token_mgr)
        data = json.loads(config_file.read_text())
        assert "prod" in data
        assert data["prod"]["client_id"] == "x"
        assert data["prod"]["client_secret"] == "y"

    def test_setup_empty_creds_dies(self, tmp_path, fake_config, fake_token_mgr):
        from qbo_cli.cli import cmd_auth_setup

        config_file = tmp_path / "config.json"
        fake_config.profile = "prod"
        args = make_args(command="auth", auth_command="setup")
        with (
            patch("qbo_cli.cli.CONFIG_PATH", config_file),
            patch("qbo_cli.cli.QBO_DIR", tmp_path),
            patch("builtins.input", side_effect=["", "", ""]),
        ):
            with pytest.raises(SystemExit):
                cmd_auth_setup(args, fake_config, fake_token_mgr)

    def test_setup_migrates_flat_config(self, tmp_path, fake_config, fake_token_mgr, capsys):
        from qbo_cli.cli import cmd_auth_setup

        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "client_id": "old-id",
                    "client_secret": "old-secret",
                    "realm_id": "old-realm",
                }
            )
        )
        fake_config.profile = "prod"
        args = make_args(command="auth", auth_command="setup")
        with (
            patch("qbo_cli.cli.CONFIG_PATH", config_file),
            patch("qbo_cli.cli.QBO_DIR", tmp_path),
            patch("builtins.input", side_effect=["", "", ""]),  # accept old defaults
        ):
            cmd_auth_setup(args, fake_config, fake_token_mgr)
        data = json.loads(config_file.read_text())
        assert "prod" in data
        assert data["prod"]["client_id"] == "old-id"
        assert data["prod"]["realm_id"] == "old-realm"
        assert "client_id" not in data  # no flat keys at top level
