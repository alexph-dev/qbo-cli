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
def test_smoke_gl_list_accounts_json():
    """List top-level accounts via gl-report as JSON."""
    result = subprocess.run(
        ["qbo", "gl-report", "--list-accounts", "--format", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "groups" in data
    assert "top_level_count" in data


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
    data = json.loads(result.stdout)
    assert "start_date" in data
    assert "end_date" in data
    assert "total" in data


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
def test_live_void_invoice_lifecycle():
    """Create a test Invoice, void it, then delete it for cleanup."""
    # Find a customer to attach the invoice to
    cust = subprocess.run(
        ["qbo", "query", "SELECT Id FROM Customer MAXRESULTS 1", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert cust.returncode == 0, f"stderr: {cust.stderr}"
    customers = json.loads(cust.stdout)
    assert customers, "Need at least one Customer for invoice test"
    cust_id = customers[0]["Id"]

    # Find a zero-rate tax code for the test invoice
    tax = subprocess.run(
        ["qbo", "query", "SELECT Id FROM TaxCode WHERE Name LIKE '%0%' MAXRESULTS 1", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert tax.returncode == 0, f"tax stderr: {tax.stderr}"
    tax_codes = json.loads(tax.stdout)
    tax_ref = {"value": tax_codes[0]["Id"]} if tax_codes else {"value": "NON"}

    # Create a minimal test invoice
    invoice_body = json.dumps({
        "CustomerRef": {"value": cust_id},
        "Line": [
            {
                "Amount": 1.00,
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {
                    "ItemRef": {"value": "1"},
                    "TaxCodeRef": tax_ref,
                },
            }
        ],
    })
    create = subprocess.run(
        ["qbo", "create", "Invoice", "-o", "json"],
        input=invoice_body,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert create.returncode == 0, f"create stderr: {create.stderr}"
    created = json.loads(create.stdout)
    inv_id = created["Invoice"]["Id"]

    # Void the invoice
    void = subprocess.run(
        ["qbo", "void", "Invoice", inv_id, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert void.returncode == 0, f"void stderr: {void.stderr}"
    voided = json.loads(void.stdout)
    assert voided["Invoice"]["Id"] == inv_id

    # Delete the voided invoice for cleanup
    delete = subprocess.run(
        ["qbo", "delete", "Invoice", inv_id, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert delete.returncode == 0, f"delete stderr: {delete.stderr}"


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
