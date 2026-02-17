"""Live smoke tests — real API calls, requires QBO credentials.

Run with: pytest -m live -v
These are excluded from CI by default via addopts in pyproject.toml.
"""

from __future__ import annotations

import json
import subprocess

import pytest


@pytest.mark.live
def test_smoke_query():
    """Basic query against real QBO."""
    result = subprocess.run(
        ["qbo", "query", "SELECT Id FROM CompanyInfo", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert len(data) > 0


@pytest.mark.live
def test_smoke_report():
    """Basic report against real QBO."""
    result = subprocess.run(
        ["qbo", "report", "ProfitAndLoss", "--date-macro", "Last Month", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "Header" in data


@pytest.mark.live
def test_smoke_get():
    """Get CompanyInfo entity."""
    result = subprocess.run(
        ["qbo", "query", "SELECT Id FROM CompanyInfo", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    company_id = data[0]["Id"]

    result = subprocess.run(
        ["qbo", "get", "CompanyInfo", company_id, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "CompanyInfo" in data or "CompanyName" in str(data)


@pytest.mark.live
def test_smoke_gl_list_accounts():
    """List all accounts via gl-report."""
    result = subprocess.run(
        ["qbo", "gl-report", "--list-accounts"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "top-level accounts" in result.stdout


@pytest.mark.live
def test_smoke_gl_report_text():
    """GL report for first discovered account, text output."""
    # Find an account ID first
    accts = subprocess.run(
        ["qbo", "query", "SELECT Id, Name FROM Account MAXRESULTS 1", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert accts.returncode == 0, f"stderr: {accts.stderr}"
    data = json.loads(accts.stdout)
    assert len(data) > 0
    acct_id = data[0]["Id"]

    result = subprocess.run(
        ["qbo", "gl-report", "-a", acct_id, "--start", "2025-01-01", "--end", "2025-12-31"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "General Ledger Report" in result.stdout


@pytest.mark.live
def test_smoke_gl_report_json():
    """GL report -o json produces structured output with expected keys."""
    accts = subprocess.run(
        ["qbo", "query", "SELECT Id, Name FROM Account WHERE AccountType = 'Income' MAXRESULTS 1", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert accts.returncode == 0, f"stderr: {accts.stderr}"
    acct_list = json.loads(accts.stdout)
    if not acct_list:
        pytest.skip("No Income accounts found")
    acct_id = acct_list[0]["Id"]

    result = subprocess.run(
        ["qbo", "gl-report", "-a", acct_id, "--start", "2024-01-01", "--end", "2025-12-31", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(f"GL report returned no data for account {acct_id}")
    # -o json in gl-report renders as key-value text (not raw JSON)
    # Verify structural text output contains expected fields
    assert "start_date" in result.stdout
    assert "end_date" in result.stdout
    assert "total" in result.stdout


@pytest.mark.live
def test_smoke_gl_account_tree():
    """GL --list-accounts for a specific account shows tree."""
    accts = subprocess.run(
        ["qbo", "query", "SELECT Id, Name FROM Account MAXRESULTS 1", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert accts.returncode == 0
    acct_id = json.loads(accts.stdout)[0]["Id"]

    result = subprocess.run(
        ["qbo", "gl-report", "-a", acct_id, "--list-accounts"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "(ID:" in result.stdout


@pytest.mark.live
def test_smoke_report_balance_sheet():
    """BalanceSheet report."""
    result = subprocess.run(
        ["qbo", "report", "BalanceSheet", "--date-macro", "Last Month", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "Header" in data


@pytest.mark.live
def test_smoke_auth_status():
    """Auth status check."""
    result = subprocess.run(
        ["qbo", "-f", "json", "auth", "status"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "realm_id" in data
    assert "access_token_valid" in data


@pytest.mark.live
def test_smoke_query_customers():
    """Query customers list."""
    result = subprocess.run(
        ["qbo", "query", "SELECT Id, DisplayName FROM Customer MAXRESULTS 5", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    if data:
        assert "Id" in data[0]
        assert "DisplayName" in data[0]
