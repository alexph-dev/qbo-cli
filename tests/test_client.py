"""Tests for QBOClient with mocked HTTP requests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from qbo_cli.client import QBOClient

# ─── Query pagination ─────────────────────────────────────────────────────────


class TestQueryPagination:
    def test_single_page(self, mock_client):
        """Less than MAX_RESULTS → no second page."""
        mock_client.request.return_value = {"QueryResponse": {"Customer": [{"Id": str(i)} for i in range(5)]}}
        results = mock_client.query("SELECT * FROM Customer")
        assert len(results) == 5
        assert mock_client.request.call_count == 1

    @pytest.mark.parametrize(
        "literal",
        [
            "'ordinary'",
            "'MAXRESULTS'",
            "'STARTPOSITION'",
            "'maxresults 1 startposition 5'",
            "'Owner''s MAXRESULTS'",
            r"'Owner\'s STARTPOSITION'",
            r"'folder\\MAXRESULTS'",
            "'MAXRESULTS' AND CompanyName = 'STARTPOSITION'",
        ],
    )
    @pytest.mark.parametrize("tail_size", [0, 1])
    def test_multi_page_with_correct_startposition(
        self, fake_config, fake_token_mgr, literal: str, tail_size: int
    ) -> None:
        """Return every row once, including with keywords inside escaped literals."""
        client = QBOClient(fake_config, fake_token_mgr)
        first_page = [{"Id": str(i)} for i in range(1000)]
        tail = [{"Id": "extra"}] if tail_size else []
        responses = []
        for page in [first_page, tail]:
            response = MagicMock(status_code=200, ok=True)
            response.json.return_value = {"QueryResponse": {"Customer": page}}
            responses.append(response)
        sql = f"SELECT * FROM Customer WHERE DisplayName = {literal}"

        with patch("qbo_cli.client.requests.request", side_effect=responses) as http:
            results = client.query(sql)

        assert results == first_page + tail
        assert [call.kwargs["params"]["query"] for call in http.call_args_list] == [
            f"{sql} STARTPOSITION 1 MAXRESULTS 1000",
            f"{sql} STARTPOSITION 1001 MAXRESULTS 1000",
        ]

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM Customer MAXRESULTS 1",
            "SELECT * FROM Customer STARTPOSITION 5",
            "SELECT * FROM Customer startposition 5 maxresults 1000",
            "SELECT * FROM Customer WHERE DisplayName = 'MAXRESULTS' MAXRESULTS 1000",
            r"SELECT * FROM Customer WHERE DisplayName = 'Owner\'s' STARTPOSITION 5",
            r"SELECT * FROM Customer WHERE DisplayName = 'folder\\' MAXRESULTS 1000",
            "SELECT * FROM Customer WHERE DisplayName = 'Owner''s' STARTPOSITION 5",
        ],
    )
    def test_explicit_pagination_preserves_range(self, fake_config, fake_token_mgr, sql: str) -> None:
        """Forward the caller's exact range once, even when the response is full."""
        client = QBOClient(fake_config, fake_token_mgr)
        rows = [{"Id": str(i)} for i in range(1000)]
        response = MagicMock(status_code=200, ok=True)
        response.json.return_value = {"QueryResponse": {"Customer": rows}}

        with patch("qbo_cli.client.requests.request", return_value=response) as http:
            results = client.query(sql)

        assert results == rows
        assert http.call_count == 1
        assert http.call_args.kwargs["params"]["query"] == sql


# ─── 401 retry ────────────────────────────────────────────────────────────────


class TestRetry401:
    def test_401_triggers_refresh_and_retry_with_new_token(self, fake_config, fake_token_mgr):
        """First call returns 401 → refresh → retry with new token succeeds."""
        client = QBOClient(fake_config, fake_token_mgr)

        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_401.ok = False

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.ok = True
        mock_200.json.return_value = {"Customer": {"Id": "1"}}

        fake_token_mgr._locked_refresh = MagicMock(return_value="new-token")

        with patch("qbo_cli.client.requests.request", side_effect=[mock_401, mock_200]) as mock_req:
            result = client.request("GET", "customer/1")

        assert result == {"Customer": {"Id": "1"}}
        fake_token_mgr._locked_refresh.assert_called_once()

        # Verify second request used the refreshed token
        second_call = mock_req.call_args_list[1]
        auth_header = second_call[1]["headers"]["Authorization"]
        assert auth_header == "Bearer new-token"


# ─── Error formatting ─────────────────────────────────────────────────────────


class TestErrorFormatting:
    def test_fault_message_extraction(self, fake_config, fake_token_mgr, capsys):
        """QBO Fault errors are extracted and printed."""
        client = QBOClient(fake_config, fake_token_mgr)

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.ok = False
        mock_resp.text = "error"
        mock_resp.json.return_value = {
            "Fault": {
                "Error": [{"Message": "Object Not Found", "Detail": "Something went wrong"}],
                "type": "ValidationFault",
            }
        }

        with (
            patch("qbo_cli.client.requests.request", return_value=mock_resp),
            pytest.raises(SystemExit),
        ):
            client.request("GET", "customer/999")

        captured = capsys.readouterr().err
        assert "Object Not Found" in captured
        assert "Something went wrong" in captured


# ─── Empty query response ────────────────────────────────────────────────────


class TestEmptyQueryResponse:
    def test_empty_query_response(self, mock_client):
        mock_client.request.return_value = {"QueryResponse": {}}
        results = mock_client.query("SELECT * FROM Customer WHERE Id = '99999'")
        assert results == []


# ─── Delete (GET + POST) ─────────────────────────────────────────────────────


class TestDelete:
    def test_delete_gets_then_posts(self, mock_client):
        """delete() does GET to fetch entity, then POST with operation=delete."""
        mock_client.request.side_effect = [
            # First call: GET to fetch current entity
            {"Customer": {"Id": "42", "SyncToken": "3", "DisplayName": "Test"}},
            # Second call: POST to delete
            {"Customer": {"Id": "42", "status": "Deleted"}},
        ]
        mock_client.delete("Customer", "42")

        assert mock_client.request.call_count == 2
        # First call: GET
        get_call = mock_client.request.call_args_list[0]
        assert get_call[0] == ("GET", "customer/42")
        # Second call: POST with operation=delete
        post_call = mock_client.request.call_args_list[1]
        assert post_call[0][0] == "POST"
        assert post_call[1]["params"]["operation"] == "delete"


# ─── Void (GET + POST) ──────────────────────────────────────────────────────


class TestVoid:
    def test_void_gets_then_posts(self, mock_client):
        """void() does GET to fetch entity, then POST with operation=void."""
        mock_client.request.side_effect = [
            {"Invoice": {"Id": "99", "SyncToken": "1", "TotalAmt": 100}},
            {"Invoice": {"Id": "99", "SyncToken": "2", "TotalAmt": 0}},
        ]
        result = mock_client.void("Invoice", "99")

        assert result == {"Invoice": {"Id": "99", "SyncToken": "2", "TotalAmt": 0}}
        assert mock_client.request.call_count == 2
        get_call = mock_client.request.call_args_list[0]
        assert get_call[0] == ("GET", "invoice/99")
        post_call = mock_client.request.call_args_list[1]
        assert post_call[0][0] == "POST"
        assert post_call[1]["params"]["operation"] == "void"

    def test_void_unwraps_entity_data(self, mock_client):
        """void() correctly unwraps entity wrapper before posting."""
        entity_inner = {"Id": "7", "SyncToken": "0", "Line": []}
        mock_client.request.side_effect = [
            {"SalesReceipt": entity_inner},
            {"SalesReceipt": {**entity_inner, "SyncToken": "1"}},
        ]
        mock_client.void("SalesReceipt", "7")

        post_call = mock_client.request.call_args_list[1]
        assert post_call[1]["json_body"] == entity_inner
