"""Tests for QBOClient with mocked HTTP requests."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from qbo_cli.cli import QBOClient


# ─── Query pagination ─────────────────────────────────────────────────────────


class TestQueryPagination:
    def test_single_page(self, mock_client):
        """Less than MAX_RESULTS → no second page."""
        mock_client.request.return_value = {
            "QueryResponse": {"Customer": [{"Id": str(i)} for i in range(5)]}
        }
        results = mock_client.query("SELECT * FROM Customer")
        assert len(results) == 5
        assert mock_client.request.call_count == 1

    def test_multi_page_with_correct_startposition(self, mock_client):
        """Exactly MAX_RESULTS on page 1 → fetches page 2 with STARTPOSITION 1001."""
        page1 = {"QueryResponse": {"Customer": [{"Id": str(i)} for i in range(1000)]}}
        page2 = {"QueryResponse": {"Customer": [{"Id": "extra"}]}}
        mock_client.request.side_effect = [page1, page2]
        results = mock_client.query("SELECT * FROM Customer")
        assert len(results) == 1001
        assert mock_client.request.call_count == 2

        # Verify second call uses correct STARTPOSITION
        second_call_params = mock_client.request.call_args_list[1][1]["params"]
        assert "STARTPOSITION 1001" in second_call_params["query"]
        assert "MAXRESULTS 1000" in second_call_params["query"]

    def test_user_maxresults_bypass(self, mock_client):
        """User specifies MAXRESULTS → skip auto-pagination, forward exact SQL."""
        mock_client.request.return_value = {
            "QueryResponse": {"Customer": [{"Id": "1"}]}
        }
        results = mock_client.query("SELECT * FROM Customer MAXRESULTS 1")
        assert len(results) == 1
        # Verify exact SQL was forwarded without modification
        actual_query = mock_client.request.call_args[1]["params"]["query"]
        assert actual_query == "SELECT * FROM Customer MAXRESULTS 1"
        assert "STARTPOSITION" not in actual_query

    def test_user_startposition_bypass(self, mock_client):
        """User specifies STARTPOSITION → skip auto-pagination."""
        mock_client.request.return_value = {
            "QueryResponse": {"Customer": [{"Id": "1"}, {"Id": "2"}]}
        }
        results = mock_client.query("SELECT * FROM Customer STARTPOSITION 5")
        assert len(results) == 2
        assert mock_client.request.call_count == 1
        actual_query = mock_client.request.call_args[1]["params"]["query"]
        assert actual_query == "SELECT * FROM Customer STARTPOSITION 5"


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

        with patch("qbo_cli.cli.requests.request", side_effect=[mock_401, mock_200]) as mock_req:
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

        with patch("qbo_cli.cli.requests.request", return_value=mock_resp):
            with pytest.raises(SystemExit):
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
        result = mock_client.delete("Customer", "42")

        assert mock_client.request.call_count == 2
        # First call: GET
        get_call = mock_client.request.call_args_list[0]
        assert get_call[0] == ("GET", "customer/42")
        # Second call: POST with operation=delete
        post_call = mock_client.request.call_args_list[1]
        assert post_call[0][0] == "POST"
        assert post_call[1]["params"]["operation"] == "delete"
