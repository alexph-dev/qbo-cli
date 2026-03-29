"""Black-box CRUD+void edge-case tests against QBO sandbox.

These tests exercise the CLI's public interface via subprocess only.
All operations run against sandbox (--sandbox flag).
Each test creates its own data and cleans up in finally blocks.

Run with: pytest -m live -k sandbox_crud -v
"""

from __future__ import annotations

import json
import subprocess
import time

import pytest


def qbo(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run qbo CLI against sandbox, return completed process."""
    return subprocess.run(
        ["uv", "run", "qbo", "--sandbox", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def qbo_json(*args: str, stdin: str | None = None) -> dict | list:
    """Run qbo CLI, parse JSON output, assert success."""
    r = qbo(*args, "-o", "json", stdin=stdin)
    assert r.returncode == 0, f"stderr: {r.stderr}"
    return json.loads(r.stdout)


def _uid() -> str:
    return str(int(time.time() * 1000))


def create_test_customer(name: str = "TestCRUD") -> str:
    """Create a customer in sandbox, return its Id."""
    body = json.dumps({"DisplayName": f"{name}_{_uid()}"})
    data = qbo_json("create", "Customer", stdin=body)
    return data["Customer"]["Id"]


def delete_customer(cid: str) -> None:
    """Best-effort deactivation of a test customer (QBO doesn't support hard delete)."""
    r = qbo("get", "Customer", cid, "-o", "json")
    if r.returncode == 0:
        customer = json.loads(r.stdout).get("Customer", {})
        customer["Active"] = False
        qbo("update", "Customer", stdin=json.dumps(customer))


# ─── Create edge cases ──────────────────────────────────────────────────────


@pytest.mark.live
def test_create_customer_minimal_fields():
    """Create with only the required field (DisplayName)."""
    name = f"Minimal_{_uid()}"
    body = json.dumps({"DisplayName": name})
    data = qbo_json("create", "Customer", stdin=body)
    cid = data["Customer"]["Id"]
    try:
        assert data["Customer"]["DisplayName"] == name
        assert "SyncToken" in data["Customer"]
    finally:
        delete_customer(cid)


@pytest.mark.live
def test_create_customer_missing_required_field():
    """Create Customer with no DisplayName — QBO may accept or reject."""
    body = json.dumps({"CompanyName": "NoDisplayName Corp"})
    r = qbo("create", "Customer", "-o", "json", stdin=body)
    # QBO may accept this (auto-generates DisplayName) or reject.
    # The test verifies the CLI doesn't crash either way.
    if r.returncode == 0:
        cid = json.loads(r.stdout)["Customer"]["Id"]
        delete_customer(cid)
    assert r.returncode in (0, 1)


@pytest.mark.live
def test_create_customer_unicode_displayname():
    """Create with unicode characters in DisplayName."""
    name = f"Test_Uni_Cafe\u0301_{_uid()}"
    body = json.dumps({"DisplayName": name})
    data = qbo_json("create", "Customer", stdin=body)
    cid = data["Customer"]["Id"]
    try:
        assert data["Customer"]["Id"]
    finally:
        delete_customer(cid)


@pytest.mark.live
def test_create_customer_extra_unknown_fields():
    """Extra fields should be ignored by QBO, not crash the CLI."""
    name = f"ExtraFields_{_uid()}"
    body = json.dumps({
        "DisplayName": name,
        "TotallyFakeField": "should be ignored",
        "AnotherBogus": 42,
    })
    r = qbo("create", "Customer", "-o", "json", stdin=body)
    if r.returncode == 0:
        cid = json.loads(r.stdout)["Customer"]["Id"]
        delete_customer(cid)
    # Either QBO ignores the fields (0) or rejects them (1). CLI shouldn't crash.
    assert r.returncode in (0, 1)


@pytest.mark.live
def test_create_with_empty_json():
    """Empty JSON body should produce a clear error, not a crash."""
    r = qbo("create", "Customer", "-o", "json", stdin="{}")
    assert r.returncode == 1
    assert r.stderr  # should have an error message


# ─── Update edge cases ──────────────────────────────────────────────────────


@pytest.mark.live
def test_update_with_stale_synctoken():
    """Update with wrong SyncToken should fail with conflict error."""
    cid = create_test_customer("StaleST")
    try:
        data = qbo_json("get", "Customer", cid)
        customer = data["Customer"]
        customer["SyncToken"] = "99999"  # stale
        customer["DisplayName"] = "ShouldFail"
        r = qbo("update", "Customer", "-o", "json", stdin=json.dumps(customer))
        assert r.returncode == 1
        assert "stale" in r.stderr.lower() or "conflict" in r.stderr.lower() or "error" in r.stderr.lower()
    finally:
        delete_customer(cid)


@pytest.mark.live
def test_update_preserves_unmodified_fields():
    """Update one field, verify other fields survive."""
    name = f"Preserve_{_uid()}"
    body = json.dumps({"DisplayName": name, "CompanyName": "OriginalCorp"})
    data = qbo_json("create", "Customer", stdin=body)
    cid = data["Customer"]["Id"]
    try:
        # Update only DisplayName
        customer = data["Customer"]
        customer["DisplayName"] = f"Updated_{name}"
        qbo_json("update", "Customer", stdin=json.dumps(customer))

        # Verify CompanyName survived
        fetched = qbo_json("get", "Customer", cid)
        assert fetched["Customer"]["CompanyName"] == "OriginalCorp"
        assert fetched["Customer"]["DisplayName"] == f"Updated_{name}"
    finally:
        delete_customer(cid)


@pytest.mark.live
def test_update_nonexistent_entity():
    """Update with a bogus ID should fail."""
    body = json.dumps({"Id": "999999999", "SyncToken": "0", "DisplayName": "Ghost"})
    r = qbo("update", "Customer", "-o", "json", stdin=body)
    assert r.returncode == 1


# ─── Delete edge cases ──────────────────────────────────────────────────────


@pytest.mark.live
def test_delete_already_deleted():
    """Delete an entity twice — second should fail."""
    # Use Invoice (Customer doesn't support hard delete in QBO)
    cust = qbo_json("query", "SELECT Id FROM Customer MAXRESULTS 1")
    cust_id = cust[0]["Id"]
    tax = qbo_json("query", "SELECT Id FROM TaxCode WHERE Name LIKE '%0%' MAXRESULTS 1")
    tax_ref = {"value": tax[0]["Id"]} if tax else {"value": "NON"}
    inv_body = json.dumps({
        "CustomerRef": {"value": cust_id},
        "Line": [{
            "Amount": 1.00,
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {"ItemRef": {"value": "1"}, "TaxCodeRef": tax_ref},
        }],
    })
    created = qbo_json("create", "Invoice", stdin=inv_body)
    inv_id = created["Invoice"]["Id"]

    r1 = qbo("delete", "Invoice", inv_id, "-o", "json")
    assert r1.returncode == 0

    r2 = qbo("delete", "Invoice", inv_id, "-o", "json")
    assert r2.returncode == 1  # already gone


@pytest.mark.live
def test_delete_nonexistent_id():
    """Delete with a bogus ID should fail cleanly."""
    r = qbo("delete", "Customer", "999999999", "-o", "json")
    assert r.returncode == 1
    assert r.stderr  # should have error message


# ─── Void edge cases ────────────────────────────────────────────────────────


@pytest.mark.live
def test_void_already_voided_invoice():
    """Void an invoice that's already voided — should fail or no-op."""
    # Create minimal invoice
    cust = qbo_json("query", "SELECT Id FROM Customer MAXRESULTS 1")
    cust_id = cust[0]["Id"]
    tax = qbo_json("query", "SELECT Id FROM TaxCode WHERE Name LIKE '%0%' MAXRESULTS 1")
    tax_ref = {"value": tax[0]["Id"]} if tax else {"value": "NON"}

    inv_body = json.dumps({
        "CustomerRef": {"value": cust_id},
        "Line": [{
            "Amount": 1.00,
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {"ItemRef": {"value": "1"}, "TaxCodeRef": tax_ref},
        }],
    })
    created = qbo_json("create", "Invoice", stdin=inv_body)
    inv_id = created["Invoice"]["Id"]
    try:
        # First void — should succeed
        r1 = qbo("void", "Invoice", inv_id, "-o", "json")
        assert r1.returncode == 0

        # Second void — already voided
        r2 = qbo("void", "Invoice", inv_id, "-o", "json")
        # QBO may succeed (idempotent) or fail. CLI shouldn't crash.
        assert r2.returncode in (0, 1)
    finally:
        qbo("delete", "Invoice", inv_id)


@pytest.mark.live
def test_void_non_voidable_entity():
    """Void a Customer (not voidable) — should fail with clear error."""
    cid = create_test_customer("NoVoid")
    try:
        r = qbo("void", "Customer", cid, "-o", "json")
        assert r.returncode == 1
        assert r.stderr
    finally:
        delete_customer(cid)


# ─── Cross-operation flows ──────────────────────────────────────────────────


@pytest.mark.live
def test_create_get_roundtrip():
    """Create entity, get it back, verify fields match."""
    name = f"Roundtrip_{_uid()}"
    body = json.dumps({"DisplayName": name, "CompanyName": "RoundtripCo"})
    created = qbo_json("create", "Customer", stdin=body)
    cid = created["Customer"]["Id"]
    try:
        fetched = qbo_json("get", "Customer", cid)
        assert fetched["Customer"]["DisplayName"] == name
        assert fetched["Customer"]["CompanyName"] == "RoundtripCo"
        assert fetched["Customer"]["Id"] == cid
    finally:
        delete_customer(cid)


@pytest.mark.live
def test_create_update_get_flow():
    """Create -> update -> get -> verify update applied."""
    name = f"Flow_{_uid()}"
    created = qbo_json("create", "Customer", stdin=json.dumps({"DisplayName": name}))
    cid = created["Customer"]["Id"]
    try:
        # Update
        customer = created["Customer"]
        customer["DisplayName"] = f"Updated_{name}"
        customer["Notes"] = "Added by test"
        qbo_json("update", "Customer", stdin=json.dumps(customer))

        # Verify
        fetched = qbo_json("get", "Customer", cid)
        assert fetched["Customer"]["DisplayName"] == f"Updated_{name}"
        assert fetched["Customer"]["Notes"] == "Added by test"
    finally:
        delete_customer(cid)


@pytest.mark.live
def test_invoice_create_void_verify_delete():
    """Full invoice lifecycle: create -> void -> verify voided state -> delete."""
    cust = qbo_json("query", "SELECT Id FROM Customer MAXRESULTS 1")
    cust_id = cust[0]["Id"]
    tax = qbo_json("query", "SELECT Id FROM TaxCode WHERE Name LIKE '%0%' MAXRESULTS 1")
    tax_ref = {"value": tax[0]["Id"]} if tax else {"value": "NON"}

    inv_body = json.dumps({
        "CustomerRef": {"value": cust_id},
        "Line": [{
            "Amount": 50.00,
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {"ItemRef": {"value": "1"}, "TaxCodeRef": tax_ref},
        }],
    })
    created = qbo_json("create", "Invoice", stdin=inv_body)
    inv_id = created["Invoice"]["Id"]
    try:
        # Void
        voided = qbo_json("void", "Invoice", inv_id)
        assert voided["Invoice"]["Id"] == inv_id

        # Verify voided state — Balance should be 0
        fetched = qbo_json("get", "Invoice", inv_id)
        assert float(fetched["Invoice"]["Balance"]) == pytest.approx(0.0)
    finally:
        qbo("delete", "Invoice", inv_id)
