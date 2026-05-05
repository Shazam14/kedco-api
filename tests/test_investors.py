"""
Tests for the investor master endpoints used by /admin/investor-share.

CRUD on /api/v1/investors. Admin-only. Validation on positive capital and
non-blank name. Returned in chronological create order so the UI list is stable.
"""
from tests.conftest import auth_header


class TestInvestorEndpoints:

    def test_empty_list(self, client, admin_user):
        r = client.get("/api/v1/investors", headers=auth_header("admintest", "admin"))
        assert r.status_code == 200
        assert r.json() == []

    def test_create_then_list(self, client, admin_user):
        r = client.post(
            "/api/v1/investors",
            headers=auth_header("admintest", "admin"),
            json={"name": "Investor A", "capital_php": 6_000_000, "monthly_rate_pct": 2.0, "note": "monthly"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["name"]             == "Investor A"
        assert body["capital_php"]      == 6_000_000
        assert body["monthly_rate_pct"] == 2.0
        assert body["note"]             == "monthly"
        assert body["created_by"]       == "admintest"

        rl = client.get("/api/v1/investors", headers=auth_header("admintest", "admin"))
        assert rl.status_code == 200
        rows = rl.json()
        assert len(rows) == 1
        assert rows[0]["name"] == "Investor A"

    def test_validation_blank_name(self, client, admin_user):
        r = client.post(
            "/api/v1/investors",
            headers=auth_header("admintest", "admin"),
            json={"name": "  ", "capital_php": 100_000, "monthly_rate_pct": 2.0},
        )
        assert r.status_code == 400

    def test_validation_zero_capital(self, client, admin_user):
        r = client.post(
            "/api/v1/investors",
            headers=auth_header("admintest", "admin"),
            json={"name": "B", "capital_php": 0, "monthly_rate_pct": 2.0},
        )
        assert r.status_code == 400

    def test_validation_negative_rate(self, client, admin_user):
        r = client.post(
            "/api/v1/investors",
            headers=auth_header("admintest", "admin"),
            json={"name": "B", "capital_php": 100_000, "monthly_rate_pct": -1.0},
        )
        assert r.status_code == 400

    def test_patch_updates_fields(self, client, admin_user):
        r = client.post(
            "/api/v1/investors",
            headers=auth_header("admintest", "admin"),
            json={"name": "A", "capital_php": 1_000_000, "monthly_rate_pct": 2.0},
        )
        inv_id = r.json()["id"]

        rp = client.patch(
            f"/api/v1/investors/{inv_id}",
            headers=auth_header("admintest", "admin"),
            json={"capital_php": 2_500_000, "monthly_rate_pct": 1.5},
        )
        assert rp.status_code == 200
        body = rp.json()
        assert body["capital_php"]      == 2_500_000
        assert body["monthly_rate_pct"] == 1.5
        assert body["name"]             == "A"  # untouched

    def test_patch_unknown_id_returns_404(self, client, admin_user):
        r = client.patch(
            "/api/v1/investors/00000000-0000-0000-0000-000000000000",
            headers=auth_header("admintest", "admin"),
            json={"capital_php": 99},
        )
        assert r.status_code == 404

    def test_delete_removes_row(self, client, admin_user):
        r = client.post(
            "/api/v1/investors",
            headers=auth_header("admintest", "admin"),
            json={"name": "Gone", "capital_php": 500_000, "monthly_rate_pct": 2.0},
        )
        inv_id = r.json()["id"]

        rd = client.delete(f"/api/v1/investors/{inv_id}", headers=auth_header("admintest", "admin"))
        assert rd.status_code == 204

        rl = client.get("/api/v1/investors", headers=auth_header("admintest", "admin"))
        assert rl.json() == []

    def test_non_admin_blocked(self, client, cashier_user):
        r = client.get("/api/v1/investors", headers=auth_header("cashiertest", "cashier"))
        assert r.status_code == 403

    def test_list_chronological_order(self, client, admin_user):
        names = ["First", "Second", "Third"]
        for n in names:
            client.post(
                "/api/v1/investors",
                headers=auth_header("admintest", "admin"),
                json={"name": n, "capital_php": 100_000, "monthly_rate_pct": 2.0},
            )
        r = client.get("/api/v1/investors", headers=auth_header("admintest", "admin"))
        assert [row["name"] for row in r.json()] == names
