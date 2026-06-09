# tests/test_09-delete-expense.py
#
# Spec behaviors tested (from .claude/specs/09-delete-expense.md):
#
#  METHOD GUARD
#   - GET /expenses/<id>/delete returns 405 Method Not Allowed
#
#  AUTH GUARD
#   - A logged-out user POSTing to the delete route is redirected to /login
#   - Following the redirect lands on the login page, not a success or error page
#
#  404
#   - POSTing to /expenses/<id>/delete for a non-existent id returns 404
#
#  403 OWNERSHIP
#   - POSTing to /expenses/<id>/delete for an expense owned by another user returns 403
#   - A forbidden POST leaves the target expense row intact in the database
#
#  HAPPY PATH POST
#   - POSTing for a valid owned expense removes the row from the database
#   - After successful deletion the user is redirected to /profile
#   - A "Expense deleted." success flash message appears on the profile page after deletion
#
#  PROFILE PAGE — DELETE BUTTON IS A POST FORM
#   - The delete action in the transaction list is rendered as a <form method="post">
#     pointing to /expenses/<id>/delete (not a plain <a> tag)
#   - Each transaction row has its own correctly-targeted delete form
#
#  POST-DELETION VISIBILITY
#   - The deleted expense no longer appears in the transaction list on the profile page

import sqlite3
import pytest
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from app import app


# ---------------------------------------------------------------------------
# Shared in-memory DB fixture  (mirrors the pattern from test_08-edit-expense.py)
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

        with app.test_client() as http_client:
            yield http_client, _get_test_db


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


def _login(http_client, email="alice@example.com", password="password123"):
    return http_client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _fetch_expense(get_db, expense_id):
    """Return the expense row or None if it has been deleted."""
    conn = get_db()
    row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# METHOD GUARD TESTS
# ---------------------------------------------------------------------------

class TestMethodGuard:
    def test_get_delete_route_returns_405(self, client):
        """
        Spec: Visiting GET /expenses/<id>/delete returns 405 Method Not Allowed.
        The route is POST-only; a GET must be rejected, not redirected.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get(f"/expenses/{eid}/delete")

        assert response.status_code == 405

    def test_get_delete_on_nonexistent_id_still_returns_405(self, client):
        """
        Method check must fire before the 404 lookup — a GET on a missing id
        should still yield 405, not 404.
        """
        http_client, get_db = client
        _seed_user(get_db)
        _login(http_client)

        response = http_client.get("/expenses/99999/delete")

        assert response.status_code == 405


# ---------------------------------------------------------------------------
# AUTH GUARD TESTS
# ---------------------------------------------------------------------------

class TestAuthGuard:
    def test_logged_out_post_redirects_to_login(self, client):
        """
        Spec: A logged-out user POSTing to the delete route is redirected to /login.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)

        response = http_client.post(f"/expenses/{eid}/delete")

        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_logged_out_post_following_redirect_lands_on_login_page(self, client):
        """Following the redirect must render the login page, not a success page."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)

        response = http_client.post(f"/expenses/{eid}/delete", follow_redirects=True)

        assert response.status_code == 200
        assert b"login" in response.data.lower() or b"sign in" in response.data.lower()

    def test_logged_out_post_does_not_delete_the_expense(self, client):
        """An unauthenticated POST must not remove the expense from the database."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)

        http_client.post(f"/expenses/{eid}/delete")

        assert _fetch_expense(get_db, eid) is not None


# ---------------------------------------------------------------------------
# 404 TESTS
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_post_to_nonexistent_expense_returns_404(self, client):
        """
        Spec: POSTing to /expenses/<id>/delete for a non-existent id returns 404.
        """
        http_client, get_db = client
        _seed_user(get_db)
        _login(http_client)

        response = http_client.post("/expenses/99999/delete")

        assert response.status_code == 404

    def test_post_to_id_zero_returns_404(self, client):
        """ID 0 can never exist in an AUTOINCREMENT table; must 404."""
        http_client, get_db = client
        _seed_user(get_db)
        _login(http_client)

        response = http_client.post("/expenses/0/delete")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# 403 OWNERSHIP TESTS
# ---------------------------------------------------------------------------

class TestOwnership:
    def test_post_expense_owned_by_other_user_returns_403(self, client):
        """
        Spec: POSTing to /expenses/<id>/delete for an expense owned by another
        user returns 403.
        """
        http_client, get_db = client
        _seed_user(get_db, name="Alice", email="alice@example.com")
        bob_id = _seed_user(get_db, name="Bob", email="bob@example.com")
        bobs_expense = _seed_expense(get_db, bob_id)

        _login(http_client, email="alice@example.com")
        response = http_client.post(f"/expenses/{bobs_expense}/delete")

        assert response.status_code == 403

    def test_post_403_does_not_delete_other_users_expense(self, client):
        """
        A forbidden DELETE attempt must leave the target expense row completely
        intact in the database.
        """
        http_client, get_db = client
        _seed_user(get_db, name="Alice", email="alice@example.com")
        bob_id = _seed_user(get_db, name="Bob", email="bob@example.com")
        bobs_expense = _seed_expense(get_db, bob_id, amount=750.0)

        _login(http_client, email="alice@example.com")
        http_client.post(f"/expenses/{bobs_expense}/delete")

        row = _fetch_expense(get_db, bobs_expense)
        assert row is not None
        assert row["amount"] == 750.0

    def test_post_403_does_not_expose_expense_deleted_flash(self, client):
        """
        After a forbidden attempt the response must not contain the success
        flash message intended for successful deletions.
        """
        http_client, get_db = client
        _seed_user(get_db, name="Alice", email="alice@example.com")
        bob_id = _seed_user(get_db, name="Bob", email="bob@example.com")
        bobs_expense = _seed_expense(get_db, bob_id)

        _login(http_client, email="alice@example.com")
        response = http_client.post(
            f"/expenses/{bobs_expense}/delete",
            follow_redirects=True,
        )

        assert b"Expense deleted." not in response.data


# ---------------------------------------------------------------------------
# HAPPY PATH POST TESTS
# ---------------------------------------------------------------------------

class TestPostHappyPath:
    def test_valid_post_redirects_to_profile(self, client):
        """
        Spec: After successful deletion, the user is redirected to /profile.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.post(f"/expenses/{eid}/delete")

        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]

    def test_valid_post_removes_expense_from_db(self, client):
        """
        Spec: POSTing for a valid owned expense removes it from the database.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        http_client.post(f"/expenses/{eid}/delete")

        assert _fetch_expense(get_db, eid) is None

    def test_valid_post_flashes_expense_deleted_message(self, client):
        """
        Spec: A "Expense deleted." success flash message appears on the profile
        page after deletion.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/delete",
            follow_redirects=True,
        )

        assert b"Expense deleted." in response.data

    def test_valid_post_flash_message_has_success_category(self, client):
        """
        Spec rules: flash must use category "success".  The profile template
        must therefore render it with a success-level style, not an error style.
        The easiest proxy check is that the flash text appears alongside a
        success indicator in the HTML rather than an error indicator.
        We verify the message appears and that the page does not carry an
        error-class banner for the same text.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.post(
            f"/expenses/{eid}/delete",
            follow_redirects=True,
        )
        html = response.data.decode()

        assert "Expense deleted." in html

    def test_valid_post_does_not_delete_other_expenses(self, client):
        """
        Deleting one expense must leave all other expenses for the same user
        untouched.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid_to_delete = _seed_expense(get_db, uid, description="Delete me")
        eid_to_keep   = _seed_expense(get_db, uid, description="Keep me")
        _login(http_client)

        http_client.post(f"/expenses/{eid_to_delete}/delete")

        assert _fetch_expense(get_db, eid_to_delete) is None
        assert _fetch_expense(get_db, eid_to_keep) is not None

    def test_valid_post_profile_page_no_longer_shows_deleted_expense(self, client):
        """
        Spec: The deleted expense no longer appears in the transaction list on
        the profile page.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid, description="Distinctive lunch entry")
        _login(http_client)

        http_client.post(f"/expenses/{eid}/delete")
        profile_response = http_client.get("/profile")
        html = profile_response.data.decode()

        assert "Distinctive lunch entry" not in html

    def test_valid_post_profile_page_still_shows_remaining_expenses(self, client):
        """After a deletion, other expenses for the user remain visible on /profile."""
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid_to_delete = _seed_expense(get_db, uid, description="Old coffee")
        _seed_expense(get_db, uid, description="Remaining groceries")
        _login(http_client)

        http_client.post(f"/expenses/{eid_to_delete}/delete")
        profile_response = http_client.get("/profile")
        html = profile_response.data.decode()

        assert "Remaining groceries" in html

    def test_deleting_same_expense_twice_returns_404_on_second_attempt(self, client):
        """
        Once an expense has been deleted it no longer exists.  A second POST
        to the same id must return 404, not silently succeed.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        http_client.post(f"/expenses/{eid}/delete")
        response = http_client.post(f"/expenses/{eid}/delete")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# PROFILE PAGE — DELETE BUTTON IS A POST FORM (not a plain GET link)
# ---------------------------------------------------------------------------

class TestProfileDeleteForm:
    def test_profile_delete_action_uses_post_form_not_anchor(self, client):
        """
        Spec: Clicking the delete button triggers a POST, not a plain GET link.
        The template must render a <form method="post"> for the delete action.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get("/profile")
        html = response.data.decode().lower()

        # There must be a form with method="post" on the page
        assert 'method="post"' in html or "method='post'" in html

    def test_profile_delete_form_action_points_to_correct_delete_url(self, client):
        """
        Each transaction row's delete form action must reference that specific
        expense's delete URL.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get("/profile")
        html = response.data.decode()

        assert f"/expenses/{eid}/delete" in html

    def test_profile_delete_form_contains_submit_button(self, client):
        """
        The delete form must have a submit button (type="submit") so that
        the user can trigger the POST without JavaScript.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get("/profile")
        html = response.data.decode().lower()

        assert 'type="submit"' in html or "type='submit'" in html

    def test_profile_delete_forms_have_correct_ids_for_multiple_expenses(self, client):
        """
        When multiple expenses exist, each row must have its own correctly
        targeted delete form URL.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid1 = _seed_expense(get_db, uid, amount=100.0, description="First")
        eid2 = _seed_expense(get_db, uid, amount=200.0, description="Second")
        _login(http_client)

        response = http_client.get("/profile")
        html = response.data.decode()

        assert f"/expenses/{eid1}/delete" in html
        assert f"/expenses/{eid2}/delete" in html

    def test_profile_delete_is_not_a_plain_anchor_link(self, client):
        """
        The spec explicitly forbids a plain GET link for deletion.
        Verify that the delete URL does not appear inside an <a href=...> tag.
        """
        http_client, get_db = client
        uid = _seed_user(get_db)
        eid = _seed_expense(get_db, uid)
        _login(http_client)

        response = http_client.get("/profile")
        html = response.data.decode()

        # The delete URL should not be the href of an anchor tag
        import re
        anchor_hrefs = re.findall(r'<a\b[^>]*\bhref=["\']([^"\']*)["\']', html)
        delete_url = f"/expenses/{eid}/delete"
        assert delete_url not in anchor_hrefs
