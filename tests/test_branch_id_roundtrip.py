"""
Locks in branch_id pass-through on GET /api/v1/transactions/today.

This was silently dropped in production once already (commit 4128b62 fixed
the response mapping). Without a test, the gap is invisible: every
transaction silently becomes "Unspecified" branch in the rider's
PHP-Balance card breakdown.
"""
from tests.conftest import auth_header


class TestTransactionsTodayReturnsBranchId:
    def test_branch_id_returned_when_set(self, client, admin_user, make_transaction):
        make_transaction(branch_id="MAIN")
        r = client.get(
            "/api/v1/transactions/today",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["branch_id"] == "MAIN"

    def test_branch_id_null_when_unset(self, client, admin_user, make_transaction):
        make_transaction()  # no branch_id set
        r = client.get(
            "/api/v1/transactions/today",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        rows = r.json()
        assert rows[0]["branch_id"] is None

    def test_terminal_id_returned_too(self, client, admin_user, make_transaction):
        """Same dropped-from-response bug class — terminal_id rides the same code path."""
        make_transaction(terminal_id="Counter 1")
        r = client.get(
            "/api/v1/transactions/today",
            headers=auth_header("admintest", "admin"),
        )
        assert r.status_code == 200
        assert r.json()[0]["terminal_id"] == "Counter 1"
