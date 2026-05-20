"""
Pending Receivables — standalone ledger of cheques/GCash/PNB transfers
sitting in three bank inboxes (GPO / CBC / MBTC), with status transitions
(PENDING / CLEARED / NEEDS_REVIEW).

Lives outside FX txn flow; admin + supervisor only.
"""
from datetime import date

from tests.conftest import auth_header, _make_user


def _create_payload(**overrides):
    base = {
        "customer_name": "Atlantic",
        "amount_php":    154_625.0,
        "method":        "CHEQUE",
        "bank_account":  "CBC",
        "entry_date":    "2026-05-18",
        "note":          None,
        "status":        "PENDING",
    }
    base.update(overrides)
    return base


class TestReceivablesCrud:
    def test_create_and_list(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(),
                        headers=auth_header("admintest", "admin"))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["customer_name"] == "Atlantic"
        assert body["amount_php"]    == 154_625.0
        assert body["bank_account"]  == "CBC"
        assert body["status"]        == "PENDING"

        r2 = client.get("/api/v1/receivables/",
                        headers=auth_header("admintest", "admin"))
        assert r2.status_code == 200
        assert len(r2.json()) == 1

    def test_create_blank_name_rejected(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(customer_name="   "),
                        headers=auth_header("admintest", "admin"))
        assert r.status_code == 400

    def test_create_invalid_bank_rejected(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(bank_account="BPI"),
                        headers=auth_header("admintest", "admin"))
        assert r.status_code == 400

    def test_create_invalid_method_rejected(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(method="BITCOIN"),
                        headers=auth_header("admintest", "admin"))
        assert r.status_code == 400

    def test_create_without_date(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(entry_date=None),
                        headers=auth_header("admintest", "admin"))
        assert r.status_code == 201
        assert r.json()["entry_date"] is None


class TestReceivablesStatusTransitions:
    def test_mark_cleared_stamps_cleared_at(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(),
                        headers=auth_header("admintest", "admin"))
        rid = r.json()["id"]
        r2 = client.patch(f"/api/v1/receivables/{rid}",
                          json={"status": "CLEARED"},
                          headers=auth_header("admintest", "admin"))
        assert r2.status_code == 200
        body = r2.json()
        assert body["status"]     == "CLEARED"
        assert body["cleared_at"] is not None
        assert body["cleared_by"] == "admintest"

    def test_revert_from_cleared_clears_stamp(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(),
                        headers=auth_header("admintest", "admin"))
        rid = r.json()["id"]
        client.patch(f"/api/v1/receivables/{rid}",
                     json={"status": "CLEARED"},
                     headers=auth_header("admintest", "admin"))
        r3 = client.patch(f"/api/v1/receivables/{rid}",
                          json={"status": "PENDING"},
                          headers=auth_header("admintest", "admin"))
        assert r3.status_code == 200
        assert r3.json()["cleared_at"] is None
        assert r3.json()["cleared_by"] is None

    def test_needs_review_status(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(customer_name="Faith",
                                             amount_php=145_050.0,
                                             entry_date=None,
                                             note="no payment"),
                        headers=auth_header("admintest", "admin"))
        rid = r.json()["id"]
        r2 = client.patch(f"/api/v1/receivables/{rid}",
                          json={"status": "NEEDS_REVIEW"},
                          headers=auth_header("admintest", "admin"))
        assert r2.status_code == 200
        assert r2.json()["status"] == "NEEDS_REVIEW"
        assert r2.json()["cleared_at"] is None

    def test_invalid_status_rejected(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(),
                        headers=auth_header("admintest", "admin"))
        rid = r.json()["id"]
        r2 = client.patch(f"/api/v1/receivables/{rid}",
                          json={"status": "BOGUS"},
                          headers=auth_header("admintest", "admin"))
        assert r2.status_code == 400


class TestReceivablesPermissions:
    def test_supervisor_can_create(self, client, db):
        _make_user(db, "treas1", "supervisor", "Treasurer 1")
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(),
                        headers=auth_header("treas1", "supervisor"))
        assert r.status_code == 201

    def test_cashier_cannot_create(self, client, db):
        _make_user(db, "casher1", "cashier", "Cashier 1")
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(),
                        headers=auth_header("casher1", "cashier"))
        assert r.status_code == 403

    def test_rider_cannot_list(self, client, db):
        _make_user(db, "rider1", "rider", "Rider 1")
        r = client.get("/api/v1/receivables/",
                       headers=auth_header("rider1", "rider"))
        assert r.status_code == 403


class TestReceivablesDelete:
    def test_delete(self, client, admin_user):
        r = client.post("/api/v1/receivables/",
                        json=_create_payload(),
                        headers=auth_header("admintest", "admin"))
        rid = r.json()["id"]
        r2 = client.delete(f"/api/v1/receivables/{rid}",
                           headers=auth_header("admintest", "admin"))
        assert r2.status_code == 204

        r3 = client.get("/api/v1/receivables/",
                        headers=auth_header("admintest", "admin"))
        assert len(r3.json()) == 0

    def test_delete_unknown_404(self, client, admin_user):
        r = client.delete("/api/v1/receivables/00000000-0000-0000-0000-000000000000",
                          headers=auth_header("admintest", "admin"))
        assert r.status_code == 404
