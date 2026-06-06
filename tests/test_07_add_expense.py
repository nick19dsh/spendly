# tests/test_07_add_expense.py
#
# Spec behaviors verified (07-add-expense.md):
#
# AUTH GUARD
#   - GET /expenses/add while logged out redirects to /login
#   - POST /expenses/add while logged out redirects to /login
#
# GET HAPPY PATH
#   - GET /expenses/add while logged in returns 200 and renders the form
#   - The form contains fields: amount, category, date, description
#   - The date field defaults to today's date (YYYY-MM-DD)
#   - All seven allowed categories are present in the rendered form
#
# POST HAPPY PATH
#   - Valid submission inserts one row into the expenses table
#   - Valid submission redirects to /profile
#   - The redirect response carries a "Expense added." success flash message
#   - description is optional — submission without it still succeeds
#   - The inserted row stores the correct user_id, amount, category, date
#
# VALIDATION ERRORS — all must re-render the form (200, not redirect)
#   - Empty amount field is rejected
#   - Non-numeric amount string is rejected
#   - Amount of zero is rejected
#   - Negative amount is rejected
#   - Category value not in the allowed list is rejected
#   - Empty category (no selection) is rejected
#   - Missing date is rejected
#   - Date in wrong format (not YYYY-MM-DD) is rejected
#
# PRE-FILL ON VALIDATION FAILURE
#   - After a failed submission the previously entered amount is present in the response body
#   - After a failed submission the previously entered description is present in the response body
#   - After a failed submission the previously entered date is present in the response body
#
# DB SIDE EFFECTS
#   - After a valid POST, exactly one new expense row exists for the test user
#   - The stored amount matches the submitted float value
#
# NAVBAR
#   - "Add Expense" nav link is present in the navbar when the user is logged in
#   - "Add Expense" nav link is absent from the navbar when the user is logged out

import sqlite3
import os
import tempfile
import pytest
from datetime import date

import database.db as db_module
from app import app
from database.db import init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """
    Provides a Flask test client wired to a fresh, isolated SQLite database.

    Strategy: monkeypatch database.db.DB_PATH to a temp file so that every
    call to get_db() — whether from app routes or from test assertions — hits
    the same isolated database.  init_db() is called once to create the schema.
    seed_db() is intentionally NOT called; tests control all data themselves.
    """
    db_file = str(tmp_path / "test_spendly.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_file)

    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client


def _register_and_login(client, name="Test User", email="test@example.com", password="password123"):
    """Register a new user and log them in. Returns the login response."""
    client.post("/register", data={"name": name, "email": email, "password": password})
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _login(client, email="test@example.com", password="password123"):
    """Log in an already-registered user."""
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _valid_form_data(**overrides):
    """Return a complete, valid add-expense form payload."""
    data = {
        "amount": "250.00",
        "category": "Food",
        "date": "2026-06-01",
        "description": "Lunch",
    }
    data.update(overrides)
    return data


def _get_expenses_for_user(email):
    """Query the test DB directly and return all expense rows for the given user."""
    conn = db_module.get_db()
    rows = conn.execute(
        "SELECT e.* FROM expenses e "
        "JOIN users u ON u.id = e.user_id "
        "WHERE u.email = ?",
        (email,),
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Auth guard — unauthenticated access
# ---------------------------------------------------------------------------

class TestAddExpenseAuthGuard:

    def test_get_while_logged_out_redirects_to_login(self, client):
        """GET /expenses/add without a session must redirect to /login."""
        response = client.get("/expenses/add")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_get_while_logged_out_follows_redirect_to_login(self, client):
        """Following the redirect from GET /expenses/add lands on /login."""
        response = client.get("/expenses/add", follow_redirects=True)
        assert response.status_code == 200
        assert b"Sign in" in response.data or b"Log in" in response.data or b"login" in response.data.lower()

    def test_post_while_logged_out_redirects_to_login(self, client):
        """POST /expenses/add without a session must redirect to /login."""
        response = client.post("/expenses/add", data=_valid_form_data())
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_post_while_logged_out_does_not_insert_expense(self, client):
        """An unauthenticated POST must not write anything to the expenses table."""
        _register_and_login(client)
        # Now log out by clearing the session, then attempt a POST
        client.get("/logout")
        client.post("/expenses/add", data=_valid_form_data())
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# GET happy path
# ---------------------------------------------------------------------------

class TestAddExpenseGet:

    def test_get_while_logged_in_returns_200(self, client):
        """GET /expenses/add for an authenticated user returns HTTP 200."""
        _register_and_login(client)
        response = client.get("/expenses/add")
        assert response.status_code == 200

    def test_get_renders_amount_input(self, client):
        """The rendered form contains an amount input field."""
        _register_and_login(client)
        response = client.get("/expenses/add")
        assert b'name="amount"' in response.data

    def test_get_renders_category_select(self, client):
        """The rendered form contains a category select element."""
        _register_and_login(client)
        response = client.get("/expenses/add")
        assert b'name="category"' in response.data

    def test_get_renders_date_input(self, client):
        """The rendered form contains a date input field."""
        _register_and_login(client)
        response = client.get("/expenses/add")
        assert b'name="date"' in response.data

    def test_get_renders_description_input(self, client):
        """The rendered form contains a description input field."""
        _register_and_login(client)
        response = client.get("/expenses/add")
        assert b'name="description"' in response.data

    def test_get_date_field_defaults_to_today(self, client):
        """The date input is pre-filled with today's date in YYYY-MM-DD format."""
        _register_and_login(client)
        response = client.get("/expenses/add")
        today_str = date.today().isoformat().encode()
        assert today_str in response.data

    def test_get_renders_all_allowed_categories(self, client):
        """All seven allowed categories from the spec appear in the form."""
        allowed_categories = [
            "Food", "Transport", "Bills", "Health",
            "Entertainment", "Shopping", "Other",
        ]
        _register_and_login(client)
        response = client.get("/expenses/add")
        for cat in allowed_categories:
            assert cat.encode() in response.data, f"Category '{cat}' missing from form"

    def test_get_form_posts_to_expenses_add(self, client):
        """The form's action attribute targets /expenses/add."""
        _register_and_login(client)
        response = client.get("/expenses/add")
        assert b"/expenses/add" in response.data


# ---------------------------------------------------------------------------
# POST happy path
# ---------------------------------------------------------------------------

class TestAddExpensePostSuccess:

    def test_valid_submission_redirects_to_profile(self, client):
        """A valid POST must redirect (302) to /profile."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data())
        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]

    def test_valid_submission_shows_success_flash(self, client):
        """After redirect to /profile, the success flash 'Expense added.' is visible."""
        _register_and_login(client)
        response = client.post(
            "/expenses/add",
            data=_valid_form_data(),
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Expense added." in response.data

    def test_valid_submission_inserts_one_row(self, client):
        """A valid POST inserts exactly one row into the expenses table."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data())
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 1

    def test_valid_submission_stores_correct_amount(self, client):
        """The stored amount equals the submitted float value."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(amount="499.99"))
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 1
        assert abs(rows[0]["amount"] - 499.99) < 0.001

    def test_valid_submission_stores_correct_category(self, client):
        """The stored category matches the submitted value."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(category="Transport"))
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 1
        assert rows[0]["category"] == "Transport"

    def test_valid_submission_stores_correct_date(self, client):
        """The stored date matches the submitted YYYY-MM-DD string."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(date="2026-05-15"))
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-05-15"

    def test_valid_submission_stores_correct_description(self, client):
        """The stored description matches the submitted value."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(description="Evening snack"))
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 1
        assert rows[0]["description"] == "Evening snack"

    def test_valid_submission_stores_correct_user_id(self, client):
        """The inserted expense is associated with the logged-in user, not another user."""
        # Register a second user to confirm the row belongs to the right user
        _register_and_login(client)
        _register_and_login(
            client,
            name="Other User",
            email="other@example.com",
            password="otherpass1",
        )
        # Log in as other@example.com and add an expense
        client.post("/expenses/add", data=_valid_form_data())

        rows_test = _get_expenses_for_user("test@example.com")
        rows_other = _get_expenses_for_user("other@example.com")

        assert len(rows_test) == 0
        assert len(rows_other) == 1

    def test_description_is_optional(self, client):
        """Submitting the form without a description must still succeed."""
        _register_and_login(client)
        data = _valid_form_data()
        data["description"] = ""
        response = client.post("/expenses/add", data=data)
        assert response.status_code == 302
        assert "/profile" in response.headers["Location"]
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 1

    def test_submission_without_description_stores_null(self, client):
        """When description is omitted, the DB stores NULL (not an empty string)."""
        _register_and_login(client)
        data = _valid_form_data()
        data["description"] = ""
        client.post("/expenses/add", data=data)
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 1
        assert rows[0]["description"] is None

    def test_expense_appears_in_profile_recent_transactions(self, client):
        """After a successful add, the expense appears in the profile's transaction list."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(description="Spec lunch"))
        profile_response = client.get("/profile")
        assert response_contains(profile_response, b"Spec lunch")

    def test_all_allowed_categories_can_be_submitted(self, client):
        """Each of the seven allowed categories can be submitted successfully."""
        allowed_categories = [
            "Food", "Transport", "Bills", "Health",
            "Entertainment", "Shopping", "Other",
        ]
        _register_and_login(client)
        for cat in allowed_categories:
            response = client.post(
                "/expenses/add",
                data=_valid_form_data(category=cat, description=f"Test {cat}"),
            )
            assert response.status_code == 302, f"Category '{cat}' was unexpectedly rejected"


# ---------------------------------------------------------------------------
# Validation errors — form must re-render (200), not redirect
# ---------------------------------------------------------------------------

class TestAddExpenseValidationErrors:

    def test_empty_amount_returns_200(self, client):
        """Empty amount must re-render the form with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(amount=""))
        assert response.status_code == 200

    def test_empty_amount_shows_error_message(self, client):
        """Empty amount must render an error message."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(amount=""))
        assert b"error" in response.data.lower() or b"amount" in response.data.lower()

    def test_empty_amount_does_not_insert_row(self, client):
        """Empty amount must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(amount=""))
        assert len(_get_expenses_for_user("test@example.com")) == 0

    def test_non_numeric_amount_returns_200(self, client):
        """A non-numeric amount string must re-render the form with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(amount="abc"))
        assert response.status_code == 200

    def test_non_numeric_amount_does_not_insert_row(self, client):
        """A non-numeric amount must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(amount="abc"))
        assert len(_get_expenses_for_user("test@example.com")) == 0

    def test_zero_amount_returns_200(self, client):
        """Amount of 0 must re-render the form with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(amount="0"))
        assert response.status_code == 200

    def test_zero_amount_does_not_insert_row(self, client):
        """Amount of 0 must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(amount="0"))
        assert len(_get_expenses_for_user("test@example.com")) == 0

    def test_negative_amount_returns_200(self, client):
        """A negative amount must re-render the form with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(amount="-50"))
        assert response.status_code == 200

    def test_negative_amount_does_not_insert_row(self, client):
        """A negative amount must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(amount="-50"))
        assert len(_get_expenses_for_user("test@example.com")) == 0

    def test_invalid_category_returns_200(self, client):
        """A category value outside the allowed list must re-render the form with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(category="Gambling"))
        assert response.status_code == 200

    def test_invalid_category_does_not_insert_row(self, client):
        """An invalid category must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(category="Gambling"))
        assert len(_get_expenses_for_user("test@example.com")) == 0

    def test_empty_category_returns_200(self, client):
        """An empty/blank category must re-render the form with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(category=""))
        assert response.status_code == 200

    def test_empty_category_does_not_insert_row(self, client):
        """An empty category must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(category=""))
        assert len(_get_expenses_for_user("test@example.com")) == 0

    def test_missing_date_returns_200(self, client):
        """An empty date field must re-render the form with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(date=""))
        assert response.status_code == 200

    def test_missing_date_does_not_insert_row(self, client):
        """An empty date must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(date=""))
        assert len(_get_expenses_for_user("test@example.com")) == 0

    def test_invalid_date_format_returns_200(self, client):
        """A date in an incorrect format (not YYYY-MM-DD) must re-render with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(date="01/06/2026"))
        assert response.status_code == 200

    def test_invalid_date_format_does_not_insert_row(self, client):
        """A date in an incorrect format must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(date="01/06/2026"))
        assert len(_get_expenses_for_user("test@example.com")) == 0

    def test_invalid_date_text_string_returns_200(self, client):
        """A date value that is plain text must re-render with HTTP 200."""
        _register_and_login(client)
        response = client.post("/expenses/add", data=_valid_form_data(date="not-a-date"))
        assert response.status_code == 200

    def test_invalid_date_text_string_does_not_insert_row(self, client):
        """A date value that is plain text must not write to the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(date="not-a-date"))
        assert len(_get_expenses_for_user("test@example.com")) == 0


# ---------------------------------------------------------------------------
# Parameterized amount boundary checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_amount", [
    "",          # empty
    "abc",       # non-numeric
    "0",         # zero
    "0.00",      # zero as float string
    "-1",        # negative integer
    "-0.01",     # negative fraction
    "  ",        # whitespace only
])
def test_invalid_amount_rejected_parametrize(client, bad_amount):
    """Parametrized: every out-of-spec amount value must result in a 200 re-render and no DB insert."""
    _register_and_login(client)
    response = client.post("/expenses/add", data=_valid_form_data(amount=bad_amount))
    assert response.status_code == 200, f"Expected 200 for amount={bad_amount!r}"
    assert len(_get_expenses_for_user("test@example.com")) == 0, (
        f"DB row was inserted for invalid amount={bad_amount!r}"
    )


@pytest.mark.parametrize("good_amount", [
    "0.01",      # minimum positive
    "1",         # integer string
    "100",       # round number
    "9999.99",   # large value
    "  250.00 ", # amount with surrounding whitespace (spec says strip)
])
def test_valid_amount_accepted_parametrize(client, good_amount):
    """Parametrized: valid positive amounts must be accepted and redirect to /profile."""
    _register_and_login(client)
    response = client.post("/expenses/add", data=_valid_form_data(amount=good_amount))
    assert response.status_code == 302, f"Expected redirect for amount={good_amount!r}"
    assert "/profile" in response.headers["Location"]


# ---------------------------------------------------------------------------
# Pre-fill on validation failure
# ---------------------------------------------------------------------------

class TestAddExpensePreFill:

    def test_amount_value_is_prefilled_after_invalid_category(self, client):
        """On validation failure (bad category), the submitted amount is echoed back in the form."""
        _register_and_login(client)
        response = client.post(
            "/expenses/add",
            data=_valid_form_data(amount="375.50", category="InvalidCat"),
        )
        assert response.status_code == 200
        assert b"375.50" in response.data

    def test_description_is_prefilled_after_invalid_amount(self, client):
        """On validation failure (bad amount), the submitted description is echoed back."""
        _register_and_login(client)
        response = client.post(
            "/expenses/add",
            data=_valid_form_data(amount="abc", description="My coffee"),
        )
        assert response.status_code == 200
        assert b"My coffee" in response.data

    def test_date_is_prefilled_after_invalid_amount(self, client):
        """On validation failure (bad amount), the submitted date is echoed back."""
        _register_and_login(client)
        response = client.post(
            "/expenses/add",
            data=_valid_form_data(amount="0", date="2026-05-20"),
        )
        assert response.status_code == 200
        assert b"2026-05-20" in response.data

    def test_amount_is_prefilled_after_missing_date(self, client):
        """On validation failure (missing date), the submitted amount is echoed back."""
        _register_and_login(client)
        response = client.post(
            "/expenses/add",
            data=_valid_form_data(amount="150.00", date=""),
        )
        assert response.status_code == 200
        assert b"150.00" in response.data

    def test_description_is_prefilled_after_missing_date(self, client):
        """On validation failure (missing date), the submitted description is echoed back."""
        _register_and_login(client)
        response = client.post(
            "/expenses/add",
            data=_valid_form_data(date="", description="Auto fare"),
        )
        assert response.status_code == 200
        assert b"Auto fare" in response.data


# ---------------------------------------------------------------------------
# Navbar visibility
# ---------------------------------------------------------------------------

class TestAddExpenseNavbar:

    def test_add_expense_link_visible_when_logged_in(self, client):
        """The 'Add Expense' nav link must appear in the rendered HTML when the user is logged in."""
        _register_and_login(client)
        # Check the navbar on any authenticated page
        response = client.get("/profile")
        assert response.status_code == 200
        assert b"Add Expense" in response.data

    def test_add_expense_link_absent_when_logged_out(self, client):
        """The 'Add Expense' nav link must NOT appear when no user is logged in."""
        response = client.get("/")
        assert b"Add Expense" not in response.data

    def test_add_expense_nav_link_points_to_correct_route(self, client):
        """The 'Add Expense' nav link href is /expenses/add."""
        _register_and_login(client)
        response = client.get("/profile")
        assert b"/expenses/add" in response.data

    def test_add_expense_link_absent_on_login_page(self, client):
        """The 'Add Expense' nav link is not shown on the public login page."""
        response = client.get("/login")
        assert b"Add Expense" not in response.data

    def test_add_expense_link_absent_on_register_page(self, client):
        """The 'Add Expense' nav link is not shown on the public register page."""
        response = client.get("/register")
        assert b"Add Expense" not in response.data


# ---------------------------------------------------------------------------
# SQL injection safety
# ---------------------------------------------------------------------------

class TestAddExpenseSQLInjection:

    def test_sql_injection_in_description_does_not_break_db(self, client):
        """A SQL injection payload in the description field is stored safely and does not corrupt the DB."""
        _register_and_login(client)
        malicious = "'); DROP TABLE expenses; --"
        response = client.post(
            "/expenses/add",
            data=_valid_form_data(description=malicious),
        )
        # Should redirect successfully
        assert response.status_code == 302
        # The expenses table must still exist and contain the row
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 1
        assert rows[0]["description"] == malicious

    def test_sql_injection_in_category_is_rejected_as_invalid(self, client):
        """A SQL injection payload used as a category is rejected because it is not in the allowed list."""
        _register_and_login(client)
        response = client.post(
            "/expenses/add",
            data=_valid_form_data(category="'; DROP TABLE expenses; --"),
        )
        assert response.status_code == 200
        assert len(_get_expenses_for_user("test@example.com")) == 0


# ---------------------------------------------------------------------------
# Multiple expenses from the same user
# ---------------------------------------------------------------------------

class TestAddExpenseMultipleEntries:

    def test_second_expense_adds_another_row(self, client):
        """Submitting the form twice creates two separate rows in the database."""
        _register_and_login(client)
        client.post("/expenses/add", data=_valid_form_data(description="First"))
        client.post("/expenses/add", data=_valid_form_data(description="Second"))
        rows = _get_expenses_for_user("test@example.com")
        assert len(rows) == 2

    def test_expenses_from_different_users_are_isolated(self, client):
        """Expenses added by user A are not visible in user B's expense rows."""
        _register_and_login(client, email="user_a@example.com", password="password123")
        client.post("/expenses/add", data=_valid_form_data(description="User A expense"))

        _register_and_login(
            client,
            name="User B",
            email="user_b@example.com",
            password="password456",
        )
        client.post("/expenses/add", data=_valid_form_data(description="User B expense"))

        rows_a = _get_expenses_for_user("user_a@example.com")
        rows_b = _get_expenses_for_user("user_b@example.com")

        assert len(rows_a) == 1
        assert rows_a[0]["description"] == "User A expense"
        assert len(rows_b) == 1
        assert rows_b[0]["description"] == "User B expense"


# ---------------------------------------------------------------------------
# Helper used in profile integration test (defined at module level)
# ---------------------------------------------------------------------------

def response_contains(response, needle: bytes) -> bool:
    """Return True if needle appears anywhere in the response body."""
    return needle in response.data
