"""Treasurer cheque-clear flow.

Two endpoints:
  GET  /api/v1/treasurer/cheques/pending    — list uncleared cheque slices
  POST /api/v1/treasurer/cheques/{id}/clear — stamp cleared_at + cleared_by

cleared_by = the treasurer who clicks; the shift aggregate then credits her drawer.
"""
import uuid

from app.models.transaction import TxnPayment, PaymentMode, PaymentStatus
from tests.conftest import auth_header


def _add_payment(db, txn, *, method=PaymentMode.CHEQUE, amount=50_000.0,
                 reference_no="CHK-001", cleared_at=None, cleared_by=None):
    p = TxnPayment(
        id=uuid.uuid4(),
        txn_id=txn.id,
        method=method,
        amount_php=amount,
        status=PaymentStatus.RECEIVED,
        reference_no=reference_no,
        cleared_at=cleared_at,
        cleared_by=cleared_by,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_pending_lists_uncleared_cheques(client, db, supervisor_user, make_transaction):
    t = make_transaction(customer="Acme Corp")
    p = _add_payment(db, t, reference_no="CHK-100")

    res = client.get("/api/v1/treasurer/cheques/pending",
                     headers=auth_header(supervisor_user.username, "supervisor"))
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["payment_id"] == str(p.id)
    assert rows[0]["txn_id"] == t.id
    assert rows[0]["customer"] == "Acme Corp"
    assert rows[0]["reference_no"] == "CHK-100"
    assert rows[0]["amount_php"] == 50_000.0


def test_pending_excludes_cleared(client, db, supervisor_user, make_transaction):
    from datetime import datetime
    t = make_transaction()
    _add_payment(db, t, cleared_at=datetime.now(), cleared_by="treasurer1")

    res = client.get("/api/v1/treasurer/cheques/pending",
                     headers=auth_header(supervisor_user.username, "supervisor"))
    assert res.status_code == 200
    assert res.json() == []


def test_pending_excludes_non_cheque_methods(client, db, supervisor_user, make_transaction):
    t = make_transaction()
    _add_payment(db, t, method=PaymentMode.GCASH)
    _add_payment(db, t, method=PaymentMode.BANK_TRANSFER)

    res = client.get("/api/v1/treasurer/cheques/pending",
                     headers=auth_header(supervisor_user.username, "supervisor"))
    assert res.status_code == 200
    assert res.json() == []


def test_pending_forbidden_for_cashier(client, db, cashier_user, make_transaction):
    t = make_transaction()
    _add_payment(db, t)

    res = client.get("/api/v1/treasurer/cheques/pending",
                     headers=auth_header(cashier_user.username, "cashier"))
    assert res.status_code == 403


def test_clear_stamps_cleared_at_and_cleared_by(client, db, supervisor_user, make_transaction):
    t = make_transaction()
    p = _add_payment(db, t)

    res = client.post(f"/api/v1/treasurer/cheques/{p.id}/clear",
                      headers=auth_header(supervisor_user.username, "supervisor"))
    assert res.status_code == 200
    body = res.json()
    assert body["payment_id"] == str(p.id)
    assert body["cleared_by"] == supervisor_user.username
    assert body["cleared_at"] is not None

    db.refresh(p)
    assert p.cleared_at is not None
    assert p.cleared_by == supervisor_user.username


def test_clear_already_cleared_returns_400(client, db, supervisor_user, make_transaction):
    from datetime import datetime
    t = make_transaction()
    p = _add_payment(db, t, cleared_at=datetime.now(), cleared_by="treasurer1")

    res = client.post(f"/api/v1/treasurer/cheques/{p.id}/clear",
                      headers=auth_header(supervisor_user.username, "supervisor"))
    assert res.status_code == 400


def test_clear_non_cheque_returns_400(client, db, supervisor_user, make_transaction):
    t = make_transaction()
    p = _add_payment(db, t, method=PaymentMode.GCASH)

    res = client.post(f"/api/v1/treasurer/cheques/{p.id}/clear",
                      headers=auth_header(supervisor_user.username, "supervisor"))
    assert res.status_code == 400


def test_clear_unknown_id_returns_404(client, supervisor_user):
    fake = uuid.uuid4()
    res = client.post(f"/api/v1/treasurer/cheques/{fake}/clear",
                      headers=auth_header(supervisor_user.username, "supervisor"))
    assert res.status_code == 404


def test_clear_forbidden_for_cashier(client, db, cashier_user, make_transaction):
    t = make_transaction()
    p = _add_payment(db, t)

    res = client.post(f"/api/v1/treasurer/cheques/{p.id}/clear",
                      headers=auth_header(cashier_user.username, "cashier"))
    assert res.status_code == 403
