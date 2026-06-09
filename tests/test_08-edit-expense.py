# tests/test_08-edit-expense.py
#
# Spec behaviors tested (from .claude/specs/08-edit-expense.md):
#
#  AUTH GUARD
#   - GET /expenses/<id>/edit redirects to /login when not logged in
#   - POST /expenses/<id>/edit redirects to /login when not logged in
#
#  404
#   - GET on a non-existent expense id returns 404
#
#  403 OWNERSHIP
#   - GET an expense owned by a different user returns 403
#   - POST an expense owned by a different user returns 403
#
#  HAPPY PATH GET
#   - Form renders 200 with existing amount, category, date, description pre-filled
#
#  HAPPY PATH POST
#   - Valid submission updates the DB row
#   - Redirects to /profile after update
#   - Flash message "Expense updated." is present after redirect
#
#  VALIDATION ERRORS (POST, logged in as owner) — form re-renders, DB unchanged:
#   - Empty amount
#   - Non-numeric amount
#   - Amount <= 0
#   - Amount > 1,000,000
#   - Invalid category (not in allowed list)
#   - Missing date
#   - Malformed date (not YYYY-MM-DD)
#   - Description longer than 200 characters
#
#  SUBMITTED VALUES PRESERVED ON VALIDATION FAILURE
#   - Re-rendered form shows submitted (not original) values
#
#  PROFILE PAGE EDIT LINKS
#   - Each transaction row has an Edit link pointing to /expenses/<id>/edit

import sqlite3
import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

import app as flask_app_module
from app import app


# ---------------------------------------------------------------------------
# Shared in-memory DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path):
    """
    Create a fresh SQLite database for every test.  Because db.py hard-codes
    DB_PATH we patch database.db.get_db (and the re-export used by
    database.queries) so every call goes to the same temp file for the
    duration of one test, giving us full isolation without touching the real
    spendly.db.
    """
    db_file = str(tmp_path / "test_spendly.db")

    def _get_test_db():
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # Patch get_db everywhere it is imported
    with patch("database.db.get_db", side_effect=_get_test_db), \
         patch("database.queries.get_db", side_effect=_get_test_db):

        # Build schema via the patched get_db
        conn = _get_test_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                email         TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                amount      REAL    NOT NULL,
                category    TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                description TEXT,
                created_at  TEXT    DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        conn.close()

        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret-key"

        with app.test_client() as client:
            yield client, _get_test_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_user(get_db, name="Alice", email="alice@example.com", password="password123"):
    """Insert a user and return their id."""
    conn = get_db()
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash(password)),
    )
    conn.commit()
    uid = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
    conn.close()
    return uid


def _seed_expense(get_db, user_id, amount=500.0, category="Food",
                  date="2026-05-10", description="Lunch"):
    """Insert an expense and return its id."""
    conn = get_db()
    conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, date, description),
    )
    conn.commit()
    eid = conn.execute(
        "SELECT id FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()["id"]
    conn.close()
    return eid


def _login(client, email="alice@example.com", password="password123"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _fetch_expense(get_db, expense_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# AUTH GUARD TESTS
# ---------------------------------------------------------------------------

class TestAuthGuard:
    def test_get_edit_redirects_to_login_when_not_logged_in(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)

        response = http_client.get(f"/expenses/{eid}/edit")

        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_post_edit_redirects_to_login_when_not_logged_in(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "999", "category": "Food",
                  "date": "2026-06-01", "description": "Test"},
        )

        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_get_edit_unauthenticated_does_not_follow_to_form(self, client):
        """Following the redirect lands on the login page, not the edit form."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)

        response = http_client.get(f"/expenses/{eid}/edit", follow_redirects=True)

        assert response.status_code == 200
        assert b"login" in response.data.lower() or b"sign in" in response.data.lower()


# ---------------------------------------------------------------------------
# 404 TESTS
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_get_nonexistent_expense_returns_404(self, client):
        http_client, get_db = client
        _seed_user(get_db)
        _login(http_client)

        response = http_client.get("/expenses/99999/edit")

        assert response.status_code == 404

    def test_post_nonexistent_expense_returns_404(self, client):
        http_client, get_db = client
        _seed_user(get_db)
        _login(http_client)

        response = http_client.post(
            "/expenses/99999/edit",
            data={"amount": "100", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 403 OWNERSHIP TESTS
# ---------------------------------------------------------------------------

class TestOwnership:
    def test_get_expense_owned_by_other_user_returns_403(self, client):
        http_client, get_db = client
        # Alice logs in
        alice_id = _seed_user(get_db, name="Alice", email="alice@example.com")
        # Bob owns the expense
        bob_id = _seed_user(get_db, name="Bob", email="bob@example.com")
        bobs_expense = _seed_expense(get_db, bob_id)

        _login(http_client, email="alice@example.com")
        response = http_client.get(f"/expenses/{bobs_expense}/edit")

        assert response.status_code == 403

    def test_post_expense_owned_by_other_user_returns_403(self, client):
        http_client, get_db = client
        alice_id = _seed_user(get_db, name="Alice", email="alice@example.com")
        bob_id = _seed_user(get_db, name="Bob", email="bob@example.com")
        bobs_expense = _seed_expense(get_db, bob_id, amount=300.0)

        _login(http_client, email="alice@example.com")
        response = http_client.post(
            f"/expenses/{bobs_expense}/edit",
            data={"amount": "999", "category": "Food",
                  "date": "2026-06-01", "description": "Hijack"},
        )

        assert response.status_code == 403

    def test_post_403_does_not_modify_other_users_expense(self, client):
        """A forbidden POST must leave the target expense row unchanged."""
        http_client, get_db = client
        alice_id = _seed_user(get_db, name="Alice", email="alice@example.com")
        bob_id = _seed_user(get_db, name="Bob", email="bob@example.com")
        bobs_expense = _seed_expense(get_db, bob_id, amount=300.0, category="Health")

        _login(http_client, email="alice@example.com")
        http_client.post(
            f"/expenses/{bobs_expense}/edit",
            data={"amount": "1", "category": "Other",
                  "date": "2026-01-01", "description": ""},
        )

        row = _fetch_expense(get_db, bobs_expense)
        assert row["amount"] == 300.0
        assert row["category"] == "Health"


# ---------------------------------------------------------------------------
# HAPPY PATH GET TESTS
# ---------------------------------------------------------------------------

class TestGetHappyPath:
    def test_get_returns_200_for_own_expense(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get(f"/expenses/{eid}/edit")

        assert response.status_code == 200

    def test_get_prefills_amount(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=1234.56)
        _login(http_client)

        response = http_client.get(f"/expenses/{eid}/edit")
        html = response.data.decode()

        assert "1234.56" in html

    def test_get_prefills_category(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, category="Transport")
        _login(http_client)

        response = http_client.get(f"/expenses/{eid}/edit")
        html = response.data.decode()

        # The selected option should be Transport
        assert "Transport" in html

    def test_get_prefills_date(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, date="2026-03-15")
        _login(http_client)

        response = http_client.get(f"/expenses/{eid}/edit")
        html = response.data.decode()

        assert "2026-03-15" in html

    def test_get_prefills_description(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, description="Coffee and snacks")
        _login(http_client)

        response = http_client.get(f"/expenses/{eid}/edit")
        html = response.data.decode()

        assert "Coffee and snacks" in html

    def test_get_form_action_points_to_correct_edit_url(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get(f"/expenses/{eid}/edit")
        html = response.data.decode()

        assert f"/expenses/{eid}/edit" in html


# ---------------------------------------------------------------------------
# HAPPY PATH POST TESTS
# ---------------------------------------------------------------------------

class TestPostHappyPath:
    def test_valid_post_redirects_to_profile(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "750", "category": "Transport",
                  "date": "2026-06-01", "description": "Bus fare"},
        )

        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]

    def test_valid_post_updates_amount_in_db(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "750", "category": "Transport",
                  "date": "2026-06-01", "description": "Bus fare"},
        )

        row = _fetch_expense(get_db, eid)
        assert row["amount"] == 750.0

    def test_valid_post_updates_category_in_db(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, category="Food")
        _login(http_client)

        http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "750", "category": "Bills",
                  "date": "2026-06-01", "description": "Electricity"},
        )

        row = _fetch_expense(get_db, eid)
        assert row["category"] == "Bills"

    def test_valid_post_updates_date_in_db(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, date="2026-01-01")
        _login(http_client)

        http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "750", "category": "Food",
                  "date": "2026-06-15", "description": ""},
        )

        row = _fetch_expense(get_db, eid)
        assert row["date"] == "2026-06-15"

    def test_valid_post_updates_description_in_db(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, description="Old description")
        _login(http_client)

        http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "750", "category": "Food",
                  "date": "2026-06-01", "description": "New description"},
        )

        row = _fetch_expense(get_db, eid)
        assert row["description"] == "New description"

    def test_valid_post_flashes_expense_updated(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "750", "category": "Food",
                  "date": "2026-06-01", "description": ""},
            follow_redirects=True,
        )

        assert b"Expense updated." in response.data

    def test_valid_post_with_empty_description_stores_none(self, client):
        """Empty description field must be stored as NULL, not empty string."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, description="Old")
        _login(http_client)

        http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "100", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        row = _fetch_expense(get_db, eid)
        assert row["description"] is None

    def test_valid_post_with_decimal_amount_persists_correctly(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=100.0)
        _login(http_client)

        http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "49.99", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        row = _fetch_expense(get_db, eid)
        assert abs(row["amount"] - 49.99) < 0.001


# ---------------------------------------------------------------------------
# VALIDATION ERROR TESTS
# ---------------------------------------------------------------------------

class TestValidationErrors:
    """Each test verifies: response is 200 (form re-render), DB row unchanged."""

    def _get_original(self, get_db, eid):
        return _fetch_expense(get_db, eid)

    def test_empty_amount_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["amount"] == 500.0

    def test_non_numeric_amount_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "abc", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["amount"] == 500.0

    def test_zero_amount_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "0", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["amount"] == 500.0

    def test_negative_amount_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "-1", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["amount"] == 500.0

    def test_amount_above_max_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "1000001", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["amount"] == 500.0

    def test_invalid_category_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, category="Food")
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "100", "category": "InvalidCat",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["category"] == "Food"

    def test_empty_category_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, category="Food")
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "100", "category": "",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["category"] == "Food"

    def test_missing_date_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, date="2026-05-10")
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "100", "category": "Food",
                  "date": "", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["date"] == "2026-05-10"

    def test_malformed_date_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, date="2026-05-10")
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "100", "category": "Food",
                  "date": "10/05/2026", "description": ""},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["date"] == "2026-05-10"

    def test_description_over_200_chars_rerenders_form(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, description="Short")
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "100", "category": "Food",
                  "date": "2026-06-01", "description": "x" * 201},
        )

        assert response.status_code == 200
        assert _fetch_expense(get_db, eid)["description"] == "Short"

    @pytest.mark.parametrize("amount,category,date,description", [
        ("",       "Food",    "2026-06-01", ""),
        ("abc",    "Food",    "2026-06-01", ""),
        ("0",      "Food",    "2026-06-01", ""),
        ("-5",     "Food",    "2026-06-01", ""),
        ("1000001","Food",    "2026-06-01", ""),
        ("100",    "BadCat",  "2026-06-01", ""),
        ("100",    "Food",    "",           ""),
        ("100",    "Food",    "01-06-2026", ""),
        ("100",    "Food",    "2026-06-01", "x" * 201),
    ])
    def test_validation_error_does_not_redirect(self, client, amount, category, date, description):
        """Every invalid combination must stay on the form (200), never redirect."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": amount, "category": category,
                  "date": date, "description": description},
        )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# SUBMITTED VALUES PRESERVED ON VALIDATION FAILURE
# ---------------------------------------------------------------------------

class TestFormPreservation:
    def test_submitted_amount_shown_on_rerender_not_original(self, client):
        """
        When validation fails, the re-rendered form must show the bad submitted
        value, not the original DB value.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        # Original amount is 500 in DB
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        # Submit a bad category with a new amount of 999 — amount is valid but
        # category will fail, causing a re-render
        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "999", "category": "NotACategory",
                  "date": "2026-06-01", "description": ""},
        )

        html = response.data.decode()
        # 999 (submitted) must appear; 500 (original) should NOT be the sole value
        assert "999" in html

    def test_submitted_description_shown_on_rerender_not_original(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, description="Original note")
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "abc",          # triggers validation failure
                  "category": "Food",
                  "date": "2026-06-01",
                  "description": "Submitted note"},
        )

        html = response.data.decode()
        assert "Submitted note" in html

    def test_submitted_date_shown_on_rerender_not_original(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, date="2026-01-01")
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "abc",          # triggers failure
                  "category": "Food",
                  "date": "2026-12-25",
                  "description": ""},
        )

        html = response.data.decode()
        assert "2026-12-25" in html

    def test_submitted_category_shown_on_rerender(self, client):
        """
        Even an invalid category value should be echoed back in the re-render
        (so the user can see exactly what they submitted).
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, category="Food")
        _login(http_client)

        # Amount is also invalid to trigger re-render via amount error first;
        # but the invalid category string should still be the one reflected.
        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "100",
                  "category": "WeirdCat",
                  "date": "2026-06-01",
                  "description": ""},
        )

        html = response.data.decode()
        assert "WeirdCat" in html


# ---------------------------------------------------------------------------
# PROFILE PAGE EDIT LINKS
# ---------------------------------------------------------------------------

class TestProfileEditLinks:
    def test_profile_shows_edit_link_for_each_transaction(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get("/profile")
        html = response.data.decode()

        assert f"/expenses/{eid}/edit" in html

    def test_profile_edit_link_text_is_edit(self, client):
        http_client, get_db = client
        uid = _seed_user(get_db)
        _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get("/profile")
        html = response.data.decode()

        assert "Edit" in html

    def test_profile_edit_link_points_to_correct_id_for_multiple_expenses(self, client):
        """Each row's Edit link must reference that row's specific expense id."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid1 = _seed_expense(get_db, uid, amount=100.0, description="First")
        eid2 = _seed_expense(get_db, uid, amount=200.0, description="Second")
        _login(http_client)

        response = http_client.get("/profile")
        html = response.data.decode()

        assert f"/expenses/{eid1}/edit" in html
        assert f"/expenses/{eid2}/edit" in html

    def test_edit_link_on_profile_leads_to_200_edit_form(self, client):
        """Clicking an Edit link (GET on the linked URL) returns 200."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get(f"/expenses/{eid}/edit")

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# BOUNDARY EDGE CASES
# ---------------------------------------------------------------------------

class TestBoundaryCases:
    def test_amount_at_exact_maximum_is_accepted(self, client):
        """1,000,000 is the upper boundary and must be valid."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "1000000", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 302
        assert _fetch_expense(get_db, eid)["amount"] == 1_000_000.0

    def test_amount_at_minimum_positive_is_accepted(self, client):
        """0.01 is the smallest valid amount."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, amount=500.0)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "0.01", "category": "Food",
                  "date": "2026-06-01", "description": ""},
        )

        assert response.status_code == 302

    def test_description_at_exactly_200_chars_is_accepted(self, client):
        """200 characters is the boundary — must be accepted."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        desc_200 = "a" * 200
        response = http_client.post(
            f"/expenses/{eid}/edit",
            data={"amount": "100", "category": "Food",
                  "date": "2026-06-01", "description": desc_200},
        )

        assert response.status_code == 302
        assert _fetch_expense(get_db, eid)["description"] == desc_200

    def test_all_valid_categories_are_accepted(self, client):
        """Every member of EXPENSE_CATEGORIES must pass validation."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        _login(http_client)
        valid_cats = ["Food", "Transport", "Bills", "Health",
                      "Entertainment", "Shopping", "Other"]

        for cat in valid_cats:
            eid = _seed_expense(get_db, uid, category="Other")
            response = http_client.post(
                f"/expenses/{eid}/edit",
                data={"amount": "50", "category": cat,
                      "date": "2026-06-01", "description": ""},
            )
            assert response.status_code == 302, \
                f"Category '{cat}' should be valid but got {response.status_code}"
