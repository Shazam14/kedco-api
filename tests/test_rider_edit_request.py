"""
HTTP-level integration tests for the rider edit-request flow.

The cashier path is covered by test_edit_requests.py (unit) and admin
approval logic is shared, so this file focuses on what's new for rider:
  • rider role accepted on POST /transactions/{id}/edit-request
  • rider role accepted on GET  /transactions/my-pending-edits
  • rider can only request edits on their own txns
  • branch_id and customer_id round-trip through proposed → approve
  • invalid customer_id rejected at submit time
"""
import uuid

import pytest

from app.models.customer import Customer
from tests.conftest import auth_header


@pytest.fixture
def make_customer(db):
    def _make(name: str, *, is_active: bool = True, merged_into_id=None) -> Customer:
        customer = Customer(
            id=uuid.uuid4(), name=name, phone=None,
            is_active=is_active, merged_into_id=merged_into_id,
            created_by="ridertest",
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
        return customer
    return _make


# ── Submit (rider role) ─────────────────────────────────────────────────────

class TestRiderSubmitEditRequest:
    def test_rider_can_request_edit_on_own_buy_with_branch_change(
        self, client, rider_user, make_transaction
    ):
        txn = make_transaction(
            type="BUY", source="RIDER", cashier="ridertest", branch_id="MAIN",
            id="RD-RIDER001",
        )
        r = client.post(
            f"/api/v1/transactions/{txn.id}/edit-request",
            headers=auth_header("ridertest", "rider"),
            json={"branch_id": "BAI"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["proposed"]["branch_id"] == "BAI"
        assert body["current_values"]["branch_id"] == "MAIN"
        assert body["requested_by"] == "ridertest"

    def test_rider_can_request_edit_on_own_sell_with_customer_id(
        self, client, rider_user, make_transaction, make_customer
    ):
        txn = make_transaction(
            type="SELL", source="RIDER", cashier="ridertest",
            id="OR-RIDER002",
        )
        c = make_customer("Hannah Wu")
        r = client.post(
            f"/api/v1/transactions/{txn.id}/edit-request",
            headers=auth_header("ridertest", "rider"),
            json={"customer_id": str(c.id), "customer": "Hannah Wu"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["proposed"]["customer_id"] == str(c.id)
        assert body["proposed"]["customer"] == "Hannah Wu"

    def test_rider_blocked_on_other_riders_txn(
        self, client, rider_user, make_transaction
    ):
        txn = make_transaction(
            type="BUY", source="RIDER", cashier="someone_else", branch_id="MAIN",
            id="RD-RIDER003",
        )
        r = client.post(
            f"/api/v1/transactions/{txn.id}/edit-request",
            headers=auth_header("ridertest", "rider"),
            json={"branch_id": "BAI"},
        )
        assert r.status_code == 403
        assert "own transactions" in r.json()["detail"]

    def test_rider_rejected_for_unknown_customer_id(
        self, client, rider_user, make_transaction
    ):
        txn = make_transaction(
            type="SELL", source="RIDER", cashier="ridertest",
            id="OR-RIDER004",
        )
        r = client.post(
            f"/api/v1/transactions/{txn.id}/edit-request",
            headers=auth_header("ridertest", "rider"),
            json={"customer_id": str(uuid.uuid4())},
        )
        assert r.status_code == 400
        assert "not found" in r.json()["detail"].lower()


# ── My pending edits (rider role) ───────────────────────────────────────────

class TestRiderMyPendingEdits:
    def test_rider_sees_their_own_pending_edit(
        self, client, rider_user, make_transaction
    ):
        txn = make_transaction(
            type="BUY", source="RIDER", cashier="ridertest", branch_id="MAIN",
            id="RD-RIDER005",
        )
        client.post(
            f"/api/v1/transactions/{txn.id}/edit-request",
            headers=auth_header("ridertest", "rider"),
            json={"branch_id": "BAI"},
        )
        r = client.get(
            "/api/v1/transactions/my-pending-edits",
            headers=auth_header("ridertest", "rider"),
        )
        assert r.status_code == 200
        assert txn.id in r.json()


# ── Approve applies new fields ──────────────────────────────────────────────

class TestApproveAppliesRiderFields:
    def test_approve_applies_branch_id_change(
        self, client, admin_user, rider_user, make_transaction
    ):
        txn = make_transaction(
            type="BUY", source="RIDER", cashier="ridertest", branch_id="MAIN",
            id="RD-RIDER006",
        )
        submit = client.post(
            f"/api/v1/transactions/{txn.id}/edit-request",
            headers=auth_header("ridertest", "rider"),
            json={"branch_id": "BAI"},
        )
        req_id = submit.json()["id"]
        r = client.post(
            f"/api/v1/admin/edit-requests/{req_id}/approve",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text

        # Re-fetch via DB to confirm the column flipped.
        from app.models.transaction import Transaction as T
        from tests.conftest import TestSessionLocal
        with TestSessionLocal() as s:
            updated = s.query(T).filter_by(id=txn.id).first()
            assert updated.branch_id == "BAI"

    def test_approve_applies_customer_id_change(
        self, client, admin_user, rider_user, make_transaction, make_customer
    ):
        txn = make_transaction(
            type="SELL", source="RIDER", cashier="ridertest",
            id="OR-RIDER007",
        )
        c = make_customer("Hannah Wu")
        submit = client.post(
            f"/api/v1/transactions/{txn.id}/edit-request",
            headers=auth_header("ridertest", "rider"),
            json={"customer_id": str(c.id), "customer": "Hannah Wu"},
        )
        req_id = submit.json()["id"]
        r = client.post(
            f"/api/v1/admin/edit-requests/{req_id}/approve",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text

        from app.models.transaction import Transaction as T
        from tests.conftest import TestSessionLocal
        with TestSessionLocal() as s:
            updated = s.query(T).filter_by(id=txn.id).first()
            assert str(updated.customer_id) == str(c.id)
            assert updated.customer == "Hannah Wu"
