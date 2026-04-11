"""QuickBooks Online API client with auto-refresh and retry."""

from __future__ import annotations

import re
import sys

import requests

from qbo_cli.auth import TokenManager
from qbo_cli.config import Config
from qbo_cli.constants import (
    DEFAULT_MAX_PAGES,
    MAX_RESULTS,
    MINOR_VERSION,
    PROD_BASE,
    SANDBOX_BASE,
)
from qbo_cli.errors import die, err_print

_PAGINATION_HINT = re.compile(r"\b(?:MAXRESULTS|STARTPOSITION)\b", re.IGNORECASE)


def _extract_entities(data: dict) -> list:
    """Pull the first list value out of a QBO QueryResponse payload."""
    for val in data.get("QueryResponse", {}).values():
        if isinstance(val, list):
            return val
    return []


def _extract_error_detail(resp: requests.Response) -> str:
    """Return a human-readable error message from a failed QBO response."""
    try:
        errors = resp.json().get("Fault", {}).get("Error", [])
        if not errors:
            return resp.text[:500]
        return "; ".join(f"{e.get('Message', '')} — {e.get('Detail', '')}" for e in errors)
    except (ValueError, AttributeError):
        return resp.text[:500]


class QBOClient:
    """QuickBooks Online API client with auto-refresh and retry."""

    def __init__(self, config: Config, token_mgr: TokenManager):
        self.config = config
        self.token_mgr = token_mgr

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _base_url(self) -> str:
        tokens = self.token_mgr._tokens or self.token_mgr.load()
        realm = tokens.get("realm_id") or self.config.realm_id
        if not realm:
            die("No realm_id. Set QBO_REALM_ID or run qbo auth init.")
        base = SANDBOX_BASE if self.config.sandbox else PROD_BASE
        return f"{base}/{realm}"

    def _http_call(self, method: str, url: str, token: str, params: dict, json_body: dict | None) -> requests.Response:
        """Single HTTP call to QBO; converts network failures into die()."""
        try:
            return requests.request(
                method,
                url,
                headers=self._headers(token),
                params=params,
                json=json_body,
                timeout=60,
            )
        except requests.ConnectionError:
            die("Network error connecting to QBO API. Check your connection.")
        except requests.Timeout:
            die("QBO API request timed out (60s). Try again later.")

    def _send_with_refresh(self, method: str, url: str, params: dict, json_body: dict | None) -> requests.Response:
        """Send request; on 401 force a token refresh and retry once."""
        token = self.token_mgr.get_valid_token()
        resp = self._http_call(method, url, token, params, json_body)
        if resp.status_code != 401:
            return resp
        err_print("Got 401, forcing token refresh...")
        token = self.token_mgr._locked_refresh(self.token_mgr.load())
        return self._http_call(method, url, token, params, json_body)

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
        raw_response: bool = False,
    ):
        """Make API request with auto-refresh and 401 retry."""
        params = dict(params) if params else {}
        params.setdefault("minorversion", MINOR_VERSION)
        url = f"{self._base_url()}/{path}"

        resp = self._send_with_refresh(method, url, params, json_body)
        if raw_response:
            return resp
        if not resp.ok:
            err_print(f"API error {resp.status_code}: {_extract_error_detail(resp)}")
            sys.exit(1)
        return resp.json()

    def query(self, sql: str, max_pages: int = DEFAULT_MAX_PAGES) -> list:
        """Run QBO query with auto-pagination."""
        # Honor explicit pagination hints; skip auto-paging.
        if _PAGINATION_HINT.search(sql):
            data = self.request("GET", "query", params={"query": sql})
            return _extract_entities(data)

        all_results: list = []
        start = 1
        for _ in range(max_pages):
            paginated_sql = f"{sql} STARTPOSITION {start} MAXRESULTS {MAX_RESULTS}"
            data = self.request("GET", "query", params={"query": paginated_sql})
            entities = _extract_entities(data)
            all_results.extend(entities)
            if len(entities) < MAX_RESULTS:
                break
            start += MAX_RESULTS

        return all_results

    def get(self, entity: str, entity_id: str) -> dict:
        return self.request("GET", f"{entity.lower()}/{entity_id}")

    def create(self, entity: str, body: dict) -> dict:
        return self.request("POST", entity.lower(), json_body=body)

    def update(self, entity: str, body: dict) -> dict:
        return self.request("POST", entity.lower(), json_body=body)

    def delete(self, entity: str, entity_id: str) -> dict:
        current = self.get(entity, entity_id)
        entity_data = current.get(entity, current)
        return self.request("POST", entity.lower(), params={"operation": "delete"}, json_body=entity_data)

    def void(self, entity: str, entity_id: str) -> dict:
        """Void a transaction by ID (GET for SyncToken, then POST with operation=void)."""
        current = self.get(entity, entity_id)
        entity_data = current.get(entity, current)
        return self.request("POST", entity.lower(), params={"operation": "void"}, json_body=entity_data)

    def report(self, report_type: str, params: dict | None = None) -> dict:
        return self.request("GET", f"reports/{report_type}", params=params)

    def raw(self, method: str, path: str, body: dict | None = None) -> dict:
        return self.request(method.upper(), path, json_body=body)
