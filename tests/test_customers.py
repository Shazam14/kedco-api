"""
Locks in the customers master-list contract used by the autocomplete picker
and the future admin merge UI.

The customer DB is the foundation for per-customer rollups (volume, frequency,
currency mix). If the FK link (`transactions.customer_id`) ever silently drops,
those rollups collapse to zero and the picker stops feeling useful — same
silent-failure mode we hit before with `branch_id`.

What this guards:
  • GET    /customers           — filter + role gate
  • POST   /customers           — create (cashier/rider/admin/supervisor)
  • GET    /customers/{id}      — fetch one
  • POST   /transactions/       — accepts and persists customer_id
  • PATCH  /transactions/{id}   — accepts customer_id; rejects unknown ids
  • Merged dupes do NOT show up in autocomplete
"""
import uuid

import pytest
from sqlalchemy import text

from app.models.customer import Customer
from tests.conftest import auth_header


# ── Factory ──────────────────────────────────────────────────────────────────

@pytest.fixture
def make_customer(db):
    def _make(name: str, *, phone: str | None = None, is_active: bool = True,
              merged_into_id=None, created_by: str = "admintest") -> Customer:
        customer = Customer(
            id=uuid.uuid4(), name=name, phone=phone,
            is_active=is_active, merged_into_id=merged_into_id,
            created_by=created_by,
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
        return customer
    return _make


# ── /customers GET ────────────────────────────────────────────────────────────

class TestListCustomers:
    def test_empty_list_when_none_seeded(self, client, admin_user):
        r = client.get("/api/v1/customers", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_active_customers(self, client, admin_user, make_customer):
        make_customer("Hannah Wu")
        make_customer("Pedro Cruz")
        r = client.get("/api/v1/customers", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        names = sorted(c["name"] for c in r.json())
        assert names == ["Hannah Wu", "Pedro Cruz"]

    def test_q_filters_case_insensitive_substring_on_name(
        self, client, admin_user, make_customer
    ):
        make_customer("Hannah Wu")
        make_customer("Pedro Cruz")
        make_customer("Maria Hannan")  # 'hann' substring lives mid-word

        r = client.get("/api/v1/customers?q=hann",
                       headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        names = sorted(c["name"] for c in r.json())
        assert names == ["Hannah Wu", "Maria Hannan"]

    def test_q_also_matches_phone(self, client, admin_user, make_customer):
        make_customer("Hannah Wu", phone="09171234567")
        make_customer("Pedro Cruz", phone="09299999999")

        r = client.get("/api/v1/customers?q=0917",
                       headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["name"] == "Hannah Wu"

    def test_inactive_customers_excluded(self, client, admin_user, make_customer):
        make_customer("Active One")
        make_customer("Soft Deleted", is_active=False)
        r = client.get("/api/v1/customers", headers=auth_header("admintest", "admin"))
        names = [c["name"] for c in r.json()]
        assert names == ["Active One"]

    def test_merged_dupes_excluded(self, client, admin_user, make_customer):
        canonical = make_customer("Hannah Wu")
        # dupe is technically active but merged into canonical → must not surface
        make_customer("Hanna Wuu", merged_into_id=canonical.id)
        r = client.get("/api/v1/customers?q=hann",
                       headers=auth_header("admintest", "admin"))
        names = [c["name"] for c in r.json()]
        assert names == ["Hannah Wu"]

    def test_cashier_rider_supervisor_can_search(
        self, client, cashier_user, rider_user, supervisor_user, make_customer
    ):
        make_customer("Hannah Wu")
        for username, role in [("cashiertest", "cashier"),
                               ("ridertest", "rider"),
                               ("supervisortest", "supervisor")]:
            r = client.get("/api/v1/customers", headers=auth_header(username, role))
            assert r.status_code == 200, f"{role} should be able to search"

    def test_unauthenticated_rejected(self, client):
        r = client.get("/api/v1/customers")
        assert r.status_code == 401


# ── /customers POST ──────────────────────────────────────────────────────────

class TestCreateCustomer:
    def test_cashier_can_create(self, client, cashier_user):
        r = client.post(
            "/api/v1/customers",
            json={"name": "Hannah Wu", "phone": "09171234567"},
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Hannah Wu"
        assert body["phone"] == "09171234567"
        assert body["is_active"] is True
        assert body["created_by"] == "cashiertest"
        assert "id" in body

    def test_rider_can_create(self, client, rider_user):
        r = client.post(
            "/api/v1/customers", json={"name": "Pedro Cruz"},
            headers=auth_header("ridertest", "rider"),
        )
        assert r.status_code == 201
        assert r.json()["created_by"] == "ridertest"

    def test_admin_can_create(self, client, admin_user):
        r = client.post(
            "/api/v1/customers", json={"name": "Maria"},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 201

    def test_name_is_trimmed(self, client, admin_user):
        r = client.post(
            "/api/v1/customers", json={"name": "  Hannah Wu  "},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 201
        assert r.json()["name"] == "Hannah Wu"

    def test_blank_name_rejected(self, client, admin_user):
        # all whitespace → fails after .strip()
        r = client.post(
            "/api/v1/customers", json={"name": "   "},
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 400

    def test_unauthenticated_rejected(self, client):
        r = client.post("/api/v1/customers", json={"name": "Hannah"})
        assert r.status_code == 401


# ── /customers/{id} GET ───────────────────────────────────────────────────────

class TestGetCustomer:
    def test_returns_customer_when_exists(self, client, admin_user, make_customer):
        c = make_customer("Hannah Wu", phone="09171234567")
        r = client.get(f"/api/v1/customers/{c.id}",
                       headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == str(c.id)
        assert body["name"] == "Hannah Wu"
        assert body["phone"] == "09171234567"

    def test_404_when_unknown(self, client, admin_user):
        r = client.get(f"/api/v1/customers/{uuid.uuid4()}",
                       headers=auth_header("admintest", "admin"))
        assert r.status_code == 404


# ── customer_id round-trip on transactions ───────────────────────────────────

@pytest.fixture
def seed_currency_and_rate(db):
    """Minimum DB state so /transactions/ POST can compute daily_avg."""
    from app.models.currency import Currency, CurrencyCategory, DailyRate, DailyPosition
    from app.core.today import get_today
    db.add(Currency(
        code="USD", name="US Dollar", flag="🇺🇸",
        category=CurrencyCategory.MAIN, decimal_places=2, sort_order=1, is_active="Y",
    ))
    db.add(DailyRate(
        date=get_today(), currency_code="USD",
        buy_rate=57.0, sell_rate=58.0, set_by="admintest",
    ))
    db.add(DailyPosition(
        date=get_today(), currency_code="USD",
        carry_in_qty=1000.0, carry_in_rate=57.5,
    ))
    db.commit()


class TestTransactionCustomerIdRoundtrip:
    def test_customer_id_persisted_on_create_and_returned(
        self, client, admin_user, make_customer, seed_currency_and_rate
    ):
        c = make_customer("Hannah Wu")
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("admintest", "admin"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "admintest",
                "customer": "Hannah Wu", "customer_id": str(c.id),
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["customer_id"] == str(c.id)
        assert body["customer"] == "Hannah Wu"

        # Round-trips through /transactions/today
        r2 = client.get("/api/v1/transactions/today",
                        headers=auth_header("admintest", "admin"))
        assert r2.status_code == 200
        rows = r2.json()
        assert len(rows) == 1
        assert rows[0]["customer_id"] == str(c.id)

    def test_unknown_customer_id_rejected(
        self, client, admin_user, seed_currency_and_rate
    ):
        bad_id = str(uuid.uuid4())
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("admintest", "admin"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "admintest",
                "customer": "Walk in", "customer_id": bad_id,
            },
        )
        assert r.status_code == 400
        assert bad_id in r.json()["detail"]

    def test_inactive_customer_id_rejected(
        self, client, admin_user, make_customer, seed_currency_and_rate
    ):
        c = make_customer("Soft Deleted", is_active=False)
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("admintest", "admin"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "admintest",
                "customer": "Soft Deleted", "customer_id": str(c.id),
            },
        )
        assert r.status_code == 400

    def test_omitting_customer_id_still_works(
        self, client, admin_user, seed_currency_and_rate
    ):
        """Walk-in path: free-text customer name only, no FK."""
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("admintest", "admin"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "admintest",
                "customer": "Just a walk-in",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["customer_id"] is None
        assert r.json()["customer"] == "Just a walk-in"

    def test_patch_can_set_customer_id_on_existing_txn(
        self, client, admin_user, make_customer, seed_currency_and_rate
    ):
        # First create a txn with no customer link
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("admintest", "admin"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "admintest",
                "customer": "Walk in",
            },
        )
        assert r.status_code == 201
        txn_id = r.json()["id"]

        # Then patch it to attach a customer
        c = make_customer("Hannah Wu")
        r2 = client.patch(
            f"/api/v1/transactions/{txn_id}",
            headers=auth_header("admintest", "admin"),
            json={"customer_id": str(c.id), "customer": "Hannah Wu"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["customer_id"] == str(c.id)

    def test_patch_rejects_unknown_customer_id(
        self, client, admin_user, seed_currency_and_rate
    ):
        r = client.post(
            "/api/v1/transactions/",
            headers=auth_header("admintest", "admin"),
            json={
                "type": "SELL", "source": "COUNTER", "currency": "USD",
                "foreign_amt": 100, "rate": 58.0, "cashier": "admintest",
                "customer": "Walk in",
            },
        )
        txn_id = r.json()["id"]
        r2 = client.patch(
            f"/api/v1/transactions/{txn_id}",
            headers=auth_header("admintest", "admin"),
            json={"customer_id": str(uuid.uuid4())},
        )
        assert r2.status_code == 400


# ── Admin-only enriched list ─────────────────────────────────────────────────

class TestAdminCustomerList:
    """
    GET /api/v1/admin/customers — list with per-customer txn_count + volume.

    Powers /admin/customers (chunk 3a). The aggregates are the whole point —
    if they regress, Ken loses the "who are my biggest customers" view.
    """

    def test_empty_list(self, client, admin_user):
        r = client.get("/api/v1/admin/customers", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        assert r.json() == []

    def test_zero_stats_for_customer_with_no_txns(self, client, admin_user, make_customer):
        make_customer("Brand New")
        r = client.get("/api/v1/admin/customers", headers=auth_header("admintest", "admin"))
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["name"] == "Brand New"
        assert rows[0]["txn_count"] == 0
        assert rows[0]["total_volume_php"] == 0.0
        assert rows[0]["last_txn_date"] is None

    def test_aggregates_count_volume_and_last_date(
        self, client, admin_user, make_customer, make_transaction, seed_currency_and_rate
    ):
        c = make_customer("Hannah Wu")
        # Two RECEIVED txns linked to Hannah
        make_transaction(php_amt=10_000.0, customer_id=c.id)
        make_transaction(php_amt=15_000.0, customer_id=c.id)
        # One unlinked walk-in — must NOT count toward Hannah's totals
        make_transaction(php_amt=99_999.0)

        r = client.get("/api/v1/admin/customers", headers=auth_header("admintest", "admin"))
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["name"] == "Hannah Wu"
        assert rows[0]["txn_count"] == 2
        assert rows[0]["total_volume_php"] == 25_000.0
        assert rows[0]["last_txn_date"] is not None

    def test_top_currencies_returned_per_customer(
        self, client, admin_user, make_customer, make_transaction, seed_currency_and_rate
    ):
        """
        Regression: chunk-6 mix query referenced Transaction.currency (which
        doesn't exist — the column is currency_code). The branch only fires
        when a customer has at least one linked txn, so a list with no
        linked txns silently passed but prod 500'd.
        """
        c = make_customer("Hannah Wu")
        make_transaction(currency="USD", php_amt=20_000.0, customer_id=c.id)
        make_transaction(currency="JPY", php_amt=5_000.0,  customer_id=c.id)

        r = client.get("/api/v1/admin/customers", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["top_currencies"] == ["USD", "JPY"]   # ordered by PHP volume desc

    def test_pending_txns_excluded_from_volume(
        self, client, admin_user, make_customer, make_transaction, seed_currency_and_rate
    ):
        c = make_customer("Hannah Wu")
        make_transaction(php_amt=10_000.0, customer_id=c.id)  # RECEIVED
        make_transaction(php_amt=5_000.0,  customer_id=c.id, payment_status="PENDING")

        rows = client.get(
            "/api/v1/admin/customers", headers=auth_header("admintest", "admin"),
        ).json()
        assert rows[0]["txn_count"] == 1
        assert rows[0]["total_volume_php"] == 10_000.0

    def test_sorted_by_volume_desc(
        self, client, admin_user, make_customer, make_transaction, seed_currency_and_rate
    ):
        small = make_customer("Small Spender")
        big   = make_customer("Big Spender")
        mid   = make_customer("Mid Spender")
        make_transaction(php_amt=1_000.0,  customer_id=small.id)
        make_transaction(php_amt=50_000.0, customer_id=big.id)
        make_transaction(php_amt=10_000.0, customer_id=mid.id)

        rows = client.get(
            "/api/v1/admin/customers", headers=auth_header("admintest", "admin"),
        ).json()
        names = [r["name"] for r in rows]
        assert names == ["Big Spender", "Mid Spender", "Small Spender"]

    def test_q_filters_by_name_or_phone(self, client, admin_user, make_customer):
        make_customer("Hannah Wu", phone="09171234567")
        make_customer("Pedro Cruz", phone="09299999999")

        rows = client.get(
            "/api/v1/admin/customers?q=hann", headers=auth_header("admintest", "admin"),
        ).json()
        assert [r["name"] for r in rows] == ["Hannah Wu"]

        rows = client.get(
            "/api/v1/admin/customers?q=0929", headers=auth_header("admintest", "admin"),
        ).json()
        assert [r["name"] for r in rows] == ["Pedro Cruz"]

    def test_inactive_excluded_by_default(self, client, admin_user, make_customer):
        make_customer("Active One")
        make_customer("Soft Deleted", is_active=False)
        rows = client.get(
            "/api/v1/admin/customers", headers=auth_header("admintest", "admin"),
        ).json()
        assert [r["name"] for r in rows] == ["Active One"]

    def test_include_inactive_flag_returns_them(self, client, admin_user, make_customer):
        make_customer("Active One")
        make_customer("Soft Deleted", is_active=False)
        rows = client.get(
            "/api/v1/admin/customers?include_inactive=true",
            headers=auth_header("admintest", "admin"),
        ).json()
        names = sorted(r["name"] for r in rows)
        assert names == ["Active One", "Soft Deleted"]

    def test_supervisor_can_access(self, client, supervisor_user, make_customer):
        make_customer("Hannah Wu")
        r = client.get(
            "/api/v1/admin/customers",
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert r.status_code == 200

    def test_cashier_blocked(self, client, cashier_user):
        r = client.get(
            "/api/v1/admin/customers",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 403

    def test_rider_blocked(self, client, rider_user):
        r = client.get(
            "/api/v1/admin/customers",
            headers=auth_header("ridertest", "rider"),
        )
        assert r.status_code == 403


# ── Admin merge ──────────────────────────────────────────────────────────────

class TestAdminMergeCustomers:
    """
    POST /api/v1/admin/customers/{canonical_id}/merge

    Repoints transactions.customer_id from each dupe to canonical, then
    soft-deletes the dupes. The whole point: dedupe Hannah Wu / Hanna Wuu
    style entries without losing the txn history they each accumulated.
    """

    def test_repoints_txns_and_soft_deletes_dupes(
        self, client, db, admin_user, make_customer, make_transaction, seed_currency_and_rate
    ):
        canonical = make_customer("Hannah Wu")
        dupe1     = make_customer("Hanna Wuu")
        dupe2     = make_customer("hannah  wu")  # extra space typo

        make_transaction(php_amt=10_000.0, customer_id=canonical.id)
        make_transaction(php_amt=5_000.0,  customer_id=dupe1.id)
        make_transaction(php_amt=7_000.0,  customer_id=dupe2.id)

        r = client.post(
            f"/api/v1/admin/customers/{canonical.id}/merge",
            headers=auth_header("admintest", "admin"),
            json={"duplicate_ids": [str(dupe1.id), str(dupe2.id)]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["canonical_id"] == str(canonical.id)
        assert body["merged_count"] == 2
        assert body["transactions_repointed"] == 2

        # The /admin/customers list now shows canonical with all three txns
        rows = client.get(
            "/api/v1/admin/customers", headers=auth_header("admintest", "admin"),
        ).json()
        assert len(rows) == 1
        assert rows[0]["name"] == "Hannah Wu"
        assert rows[0]["txn_count"] == 3
        assert rows[0]["total_volume_php"] == 22_000.0

        # And the dupes are gone from the active list, but visible with include_inactive
        all_rows = client.get(
            "/api/v1/admin/customers?include_inactive=true",
            headers=auth_header("admintest", "admin"),
        ).json()
        names = sorted(r["name"] for r in all_rows)
        assert names == ["Hanna Wuu", "Hannah Wu", "hannah  wu"]

    def test_picker_no_longer_returns_merged_dupes(
        self, client, admin_user, make_customer, make_transaction, seed_currency_and_rate
    ):
        canonical = make_customer("Hannah Wu")
        dupe = make_customer("Hanna Wuu")
        client.post(
            f"/api/v1/admin/customers/{canonical.id}/merge",
            headers=auth_header("admintest", "admin"),
            json={"duplicate_ids": [str(dupe.id)]},
        )
        rows = client.get(
            "/api/v1/customers?q=hann", headers=auth_header("admintest", "admin"),
        ).json()
        names = [r["name"] for r in rows]
        assert names == ["Hannah Wu"]

    def test_self_merge_rejected(self, client, admin_user, make_customer):
        c = make_customer("Hannah")
        r = client.post(
            f"/api/v1/admin/customers/{c.id}/merge",
            headers=auth_header("admintest", "admin"),
            json={"duplicate_ids": [str(c.id)]},
        )
        assert r.status_code == 400

    def test_unknown_canonical_404(self, client, admin_user, make_customer):
        dupe = make_customer("Hanna")
        r = client.post(
            f"/api/v1/admin/customers/{uuid.uuid4()}/merge",
            headers=auth_header("admintest", "admin"),
            json={"duplicate_ids": [str(dupe.id)]},
        )
        assert r.status_code == 404

    def test_inactive_canonical_rejected(self, client, admin_user, make_customer):
        canonical = make_customer("Soft Deleted", is_active=False)
        dupe = make_customer("Hanna")
        r = client.post(
            f"/api/v1/admin/customers/{canonical.id}/merge",
            headers=auth_header("admintest", "admin"),
            json={"duplicate_ids": [str(dupe.id)]},
        )
        assert r.status_code == 400

    def test_already_merged_dupe_rejected(self, client, admin_user, make_customer):
        canonical_a = make_customer("Hannah Wu")
        canonical_b = make_customer("Pedro Cruz")
        dupe        = make_customer("Hanna Wuu", merged_into_id=canonical_a.id)
        r = client.post(
            f"/api/v1/admin/customers/{canonical_b.id}/merge",
            headers=auth_header("admintest", "admin"),
            json={"duplicate_ids": [str(dupe.id)]},
        )
        assert r.status_code == 400
        assert "already merged" in r.json()["detail"].lower()

    def test_unknown_dupe_id_rejected(self, client, admin_user, make_customer):
        canonical = make_customer("Hannah Wu")
        r = client.post(
            f"/api/v1/admin/customers/{canonical.id}/merge",
            headers=auth_header("admintest", "admin"),
            json={"duplicate_ids": [str(uuid.uuid4())]},
        )
        assert r.status_code == 400

    def test_supervisor_blocked_admin_only(self, client, supervisor_user, make_customer):
        a = make_customer("A"); b = make_customer("B")
        r = client.post(
            f"/api/v1/admin/customers/{a.id}/merge",
            headers=auth_header("supervisortest", "supervisor"),
            json={"duplicate_ids": [str(b.id)]},
        )
        assert r.status_code == 403


# ── Per-customer detail (chunk 4) ────────────────────────────────────────────

class TestAdminCustomerDetail:
    """
    GET /api/v1/admin/customers/{id}/detail

    Powers /admin/customers/{id} — the per-customer payoff page.
    Returns aggregates + currency mix + weekly/annual rollups + recent txns.
    """

    def test_404_when_unknown(self, client, admin_user):
        r = client.get(
            f"/api/v1/admin/customers/{uuid.uuid4()}/detail",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 404

    def test_zero_aggregates_when_customer_has_no_txns(
        self, client, admin_user, make_customer
    ):
        c = make_customer("Brand New", phone="09171111111")
        r = client.get(
            f"/api/v1/admin/customers/{c.id}/detail",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["customer"]["name"] == "Brand New"
        assert body["customer"]["phone"] == "09171111111"
        assert body["stats"]["txn_count"] == 0
        assert body["stats"]["total_volume_php"] == 0.0
        assert body["stats"]["last_txn_date"] is None
        assert body["stats"]["first_txn_date"] is None
        assert body["currency_mix"] == []
        assert body["weekly"] == []
        assert body["annual"] == []
        assert body["recent_transactions"] == []

    def test_full_aggregates_populated(
        self, client, admin_user, make_customer, make_transaction, seed_currency_and_rate, db
    ):
        c = make_customer("Hannah Wu")
        # Two USD txns + one EUR txn, plus a PENDING that must NOT count
        from app.models.currency import Currency, CurrencyCategory
        db.add(Currency(
            code="EUR", name="Euro", flag="🇪🇺",
            category=CurrencyCategory.MAIN, decimal_places=2, sort_order=2, is_active="Y",
        ))
        db.commit()
        make_transaction(currency="USD", foreign_amt=100, php_amt=10_000.0, customer_id=c.id)
        make_transaction(currency="USD", foreign_amt=200, php_amt=20_000.0, customer_id=c.id)
        make_transaction(currency="EUR", foreign_amt=50,  php_amt=4_000.0,  customer_id=c.id)
        make_transaction(currency="USD", foreign_amt=99,  php_amt=99_999.0, customer_id=c.id, payment_status="PENDING")

        body = client.get(
            f"/api/v1/admin/customers/{c.id}/detail",
            headers=auth_header("admintest", "admin"),
        ).json()

        # Aggregates exclude PENDING
        assert body["stats"]["txn_count"] == 3
        assert body["stats"]["total_volume_php"] == 34_000.0
        assert body["stats"]["last_txn_date"] is not None
        assert body["stats"]["first_txn_date"] is not None

        # Currency mix sorted by total_php desc — USD (30K) before EUR (4K)
        mix = body["currency_mix"]
        assert [m["currency"] for m in mix] == ["USD", "EUR"]
        usd = next(m for m in mix if m["currency"] == "USD")
        assert usd["txn_count"] == 2
        assert usd["total_foreign"] == 300
        assert usd["total_php"] == 30_000.0

        # Recent transactions: 3 RECEIVED rows
        assert len(body["recent_transactions"]) == 3
        for t in body["recent_transactions"]:
            assert t["payment_status"] == "RECEIVED"

        # Weekly + annual buckets each have at least one row (today's bucket)
        assert len(body["weekly"]) >= 1
        assert len(body["annual"]) >= 1

    def test_includes_txns_repointed_via_merge(
        self, client, admin_user, make_customer, make_transaction, seed_currency_and_rate
    ):
        """After merging, the canonical's detail page should include the dupe's old txns."""
        canonical = make_customer("Hannah Wu")
        dupe      = make_customer("Hanna Wuu")
        make_transaction(php_amt=10_000.0, customer_id=canonical.id)
        make_transaction(php_amt=5_000.0,  customer_id=dupe.id)

        client.post(
            f"/api/v1/admin/customers/{canonical.id}/merge",
            headers=auth_header("admintest", "admin"),
            json={"duplicate_ids": [str(dupe.id)]},
        )

        body = client.get(
            f"/api/v1/admin/customers/{canonical.id}/detail",
            headers=auth_header("admintest", "admin"),
        ).json()
        assert body["stats"]["txn_count"] == 2
        assert body["stats"]["total_volume_php"] == 15_000.0

    def test_supervisor_can_access(self, client, supervisor_user, make_customer):
        c = make_customer("Hannah Wu")
        r = client.get(
            f"/api/v1/admin/customers/{c.id}/detail",
            headers=auth_header("supervisortest", "supervisor"),
        )
        assert r.status_code == 200

    def test_cashier_blocked(self, client, cashier_user, make_customer):
        c = make_customer("Hannah Wu")
        r = client.get(
            f"/api/v1/admin/customers/{c.id}/detail",
            headers=auth_header("cashiertest", "cashier"),
        )
        assert r.status_code == 403
