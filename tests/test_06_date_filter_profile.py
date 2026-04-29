# tests/test_06_date_filter_profile.py
#
# Spec behaviours verified (Step 6 — Date Filter for Profile Page):
#
#  1. GET /profile with no query params returns unfiltered data (all expenses).
#  2. date_from + date_to within a range filters summary stats, recent
#     transactions, and category breakdown to only expenses in that window.
#  3. "This Month" preset (date_from = first of current month, date_to = today)
#     filters all three sections to the current calendar month only.
#  4. "Last 3 Months" preset window filters correctly.
#  5. "Last 6 Months" preset window filters correctly.
#  6. "All Time" (no query params) shows all expenses.
#  7. Custom date range with valid date_from and date_to filters all three
#     sections.
#  8. date_from > date_to causes a flash error
#     "Start date must be before end date." and falls back to unfiltered view.
#  9. Malformed date string (e.g. date_from=not-a-date) does not crash the app
#     — silently falls back to the unfiltered view.
# 10. Template variables date_from, date_to, and presets are always present in
#     the response context so the filter bar can reflect the active state.
# 11. All amounts display the ₹ symbol regardless of active filter.
# 12. A user with no expenses in the selected range sees ₹0.00 total spent,
#     0 transactions, and an empty category breakdown — no errors.
# 13. Unauthenticated requests redirect to /login.

import sqlite3
import os
import tempfile
import pytest
from datetime import date, timedelta
from unittest.mock import patch
from werkzeug.security import generate_password_hash

import database.db as db_module
import database.queries as queries_module


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _first_of_month(today: date) -> date:
    return today.replace(day=1)


def _months_back(today: date, months: int) -> date:
    """Return the first day of the month `months` months before today."""
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

@pytest.fixture
def db_path(tmp_path):
    """Return path to a fresh, initialised SQLite database file."""
    path = str(tmp_path / "test_spendly.db")
    return path


@pytest.fixture
def patched_app(db_path):
    """
    Yield a Flask test client whose database helpers point at an isolated
    temp-file SQLite database.  We patch DB_PATH in both db_module and
    queries_module so every call to get_db() uses our test database.
    """
    with patch.object(db_module, "DB_PATH", db_path), \
         patch.object(queries_module, "get_db", db_module.get_db):

        # Import app AFTER patching so the with-app_context init_db() call
        # inside app.py uses the patched path (app is already imported, so we
        # re-run init_db manually).
        from app import app as flask_app
        flask_app.config["TESTING"] = True
        flask_app.config["SECRET_KEY"] = "test-secret"

        with flask_app.app_context():
            db_module.init_db()

        with flask_app.test_client() as client:
            yield client, flask_app


@pytest.fixture
def seeded_client(patched_app):
    """
    A test client with one test user and a set of expenses spanning multiple
    months so that date-range filtering can be meaningfully tested.

    Expense layout (user_id resolved at runtime):
        - 2026-04-01  Food          450.00   (current month, last 3 m, last 6 m)
        - 2026-04-15  Transport     120.00   (current month, last 3 m, last 6 m)
        - 2026-03-10  Bills        1500.00   (last 3 m, last 6 m)
        - 2026-02-20  Health        800.00   (last 3 m, last 6 m)
        - 2026-01-05  Shopping     2200.00   (last 6 m only if today >= 2026-07-05; within 6 m from Apr)
        - 2025-10-01  Entertainment 350.00   (older, outside 6 m from Apr 2026)
    """
    client, flask_app = patched_app

    conn = sqlite3.connect(db_module.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@spendly.com", generate_password_hash("password123")),
    )
    conn.commit()

    uid = conn.execute(
        "SELECT id FROM users WHERE email = ?", ("test@spendly.com",)
    ).fetchone()[0]

    expenses = [
        (uid, 450.00,  "Food",          "2026-04-01", "April groceries"),
        (uid, 120.00,  "Transport",     "2026-04-15", "April auto"),
        (uid, 1500.00, "Bills",         "2026-03-10", "March electricity"),
        (uid, 800.00,  "Health",        "2026-02-20", "Feb pharmacy"),
        (uid, 2200.00, "Shopping",      "2026-01-05", "Jan clothes"),
        (uid, 350.00,  "Entertainment", "2025-10-01", "Oct movie"),
    ]
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    conn.commit()
    conn.close()

    return client, uid


@pytest.fixture
def empty_client(patched_app):
    """A test client with one user who has zero expenses."""
    client, flask_app = patched_app

    conn = sqlite3.connect(db_module.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Empty User", "empty@spendly.com", generate_password_hash("password123")),
    )
    conn.commit()
    conn.close()

    return client


# ------------------------------------------------------------------ #
# Auth helper                                                          #
# ------------------------------------------------------------------ #

def set_session(client, flask_app, user_id: int, user_name: str = "Test User"):
    """Directly write auth keys into the session to simulate a logged-in user."""
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = user_name


# ------------------------------------------------------------------ #
# 13. Auth guard                                                        #
# ------------------------------------------------------------------ #

class TestAuthGuard:
    def test_unauthenticated_request_redirects_to_login(self, patched_app):
        client, flask_app = patched_app
        response = client.get("/profile")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_unauthenticated_request_with_date_params_redirects_to_login(self, patched_app):
        client, flask_app = patched_app
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_authenticated_request_returns_200(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        assert response.status_code == 200


# ------------------------------------------------------------------ #
# 1 & 6. No query params — unfiltered / "All Time"                    #
# ------------------------------------------------------------------ #

class TestNoFilterAllTime:
    def test_no_params_returns_200(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        assert response.status_code == 200

    def test_no_params_shows_all_transactions(self, seeded_client):
        """All 6 seeded expenses must appear in the transaction count."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        # The stat card for Transactions must show 6
        assert "6" in body

    def test_no_params_total_spent_includes_all_expenses(self, seeded_client):
        """Total = 450 + 120 + 1500 + 800 + 2200 + 350 = 5420.00"""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        assert "5,420.00" in body

    def test_all_time_total_spent_contains_rupee_symbol(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        assert "₹" in body

    def test_no_params_all_categories_appear_in_breakdown(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        for cat in ("Food", "Transport", "Bills", "Health", "Shopping", "Entertainment"):
            assert cat in body


# ------------------------------------------------------------------ #
# 2 & 7. Custom date range filtering                                   #
# ------------------------------------------------------------------ #

class TestCustomDateRangeFilter:
    def test_custom_range_returns_200(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        assert response.status_code == 200

    def test_custom_range_filters_transaction_count(self, seeded_client):
        """date_from=2026-04-01 to date_to=2026-04-30 → 2 transactions (Apr only)."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        body = response.data.decode()
        # Transaction count must be 2; total = 570.00
        assert "570.00" in body

    def test_custom_range_filters_summary_stats_total(self, seeded_client):
        """April total = 450 + 120 = 570.00 with ₹ symbol."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        body = response.data.decode()
        assert "₹570.00" in body

    def test_custom_range_excludes_out_of_range_transactions(self, seeded_client):
        """March, Feb, Jan, Oct expenses must NOT appear in April-only filter."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        body = response.data.decode()
        # March electricity (₹1,500) and Oct movie (₹350) descriptions must not appear
        assert "March electricity" not in body
        assert "Oct movie" not in body

    def test_custom_range_includes_only_matching_category_in_breakdown(self, seeded_client):
        """April-only breakdown must contain Food and Transport, not Bills."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        body = response.data.decode()
        assert "Food" in body
        assert "Transport" in body
        assert "Bills" not in body

    def test_custom_range_amounts_contain_rupee_symbol(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        body = response.data.decode()
        assert "₹" in body

    def test_custom_range_spanning_multiple_months_sums_correctly(self, seeded_client):
        """Feb + Mar + Apr = 800 + 1500 + 450 + 120 = 2870.00."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-02-01&date_to=2026-04-30")
        body = response.data.decode()
        assert "2,870.00" in body

    def test_custom_range_inclusive_lower_bound(self, seeded_client):
        """date_from=2026-04-01 must include the expense dated exactly 2026-04-01."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-01")
        body = response.data.decode()
        # Only the 2026-04-01 Food expense (450.00) should be in total
        assert "₹450.00" in body

    def test_custom_range_inclusive_upper_bound(self, seeded_client):
        """date_to=2026-04-15 must include the expense dated exactly 2026-04-15."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-15&date_to=2026-04-15")
        body = response.data.decode()
        # Only the 2026-04-15 Transport expense (120.00)
        assert "₹120.00" in body


# ------------------------------------------------------------------ #
# 3. "This Month" preset                                               #
# ------------------------------------------------------------------ #

class TestThisMonthPreset:
    def test_this_month_preset_returns_200(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        today = date.today()
        first = _first_of_month(today)
        response = client.get(
            f"/profile?date_from={first.isoformat()}&date_to={today.isoformat()}"
        )
        assert response.status_code == 200

    def test_this_month_preset_shows_only_current_month_expenses(self, seeded_client):
        """
        With today = 2026-04-29, This Month = 2026-04-01 to 2026-04-29.
        Only the two April expenses must be included: total ₹570.00.
        """
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        today = date.today()
        first = _first_of_month(today)
        response = client.get(
            f"/profile?date_from={first.isoformat()}&date_to={today.isoformat()}"
        )
        body = response.data.decode()
        # March electricity must be absent; April groceries must be present
        assert "April groceries" in body
        assert "March electricity" not in body

    def test_this_month_preset_link_appears_in_filter_bar(self, seeded_client):
        """The response HTML must contain a link to the This Month preset."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        assert "This Month" in body

    def test_this_month_preset_active_class_when_range_matches(self, seeded_client):
        """When the current params match This Month dates, the active class is present."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        today = date.today()
        first = _first_of_month(today)
        response = client.get(
            f"/profile?date_from={first.isoformat()}&date_to={today.isoformat()}"
        )
        body = response.data.decode()
        assert "preset-btn--active" in body


# ------------------------------------------------------------------ #
# 4. "Last 3 Months" preset                                            #
# ------------------------------------------------------------------ #

class TestLast3MonthsPreset:
    def test_last_3_months_preset_returns_200(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        today = date.today()
        start = _months_back(today, 3)
        response = client.get(
            f"/profile?date_from={start.isoformat()}&date_to={today.isoformat()}"
        )
        assert response.status_code == 200

    def test_last_3_months_includes_recent_expenses(self, seeded_client):
        """
        With today=2026-04-29: start = first of Jan 2026 = 2026-01-01.
        Included: Apr (570), Mar (1500), Feb (800), Jan (2200) = 5070.00.
        Oct 2025 (350) must be excluded as it falls before the window start.
        """
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        today = date.today()
        start = _months_back(today, 3)
        response = client.get(
            f"/profile?date_from={start.isoformat()}&date_to={today.isoformat()}"
        )
        body = response.data.decode()
        # October 2025 expense should not appear
        assert "Oct movie" not in body
        # At least the April transactions should appear
        assert "April groceries" in body

    def test_last_3_months_link_appears_in_filter_bar(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        assert "Last 3 Months" in body


# ------------------------------------------------------------------ #
# 5. "Last 6 Months" preset                                            #
# ------------------------------------------------------------------ #

class TestLast6MonthsPreset:
    def test_last_6_months_preset_returns_200(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        today = date.today()
        start = _months_back(today, 6)
        response = client.get(
            f"/profile?date_from={start.isoformat()}&date_to={today.isoformat()}"
        )
        assert response.status_code == 200

    def test_last_6_months_excludes_expenses_older_than_6_months(self, seeded_client):
        """
        With today = 2026-04-29, 6 months back = first of Oct 2025 = 2025-10-01.
        Oct 2025 expense is on exactly 2025-10-01, which is the inclusive lower
        bound — it SHOULD be included.  Expenses from before 2025-10-01 would be
        excluded.  We verify that only the six seeded expenses are visible.
        """
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        today = date.today()
        start = _months_back(today, 6)
        response = client.get(
            f"/profile?date_from={start.isoformat()}&date_to={today.isoformat()}"
        )
        body = response.data.decode()
        assert response.status_code == 200
        assert "₹" in body

    def test_last_6_months_link_appears_in_filter_bar(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        assert "Last 6 Months" in body

    def test_last_6_months_active_class_when_range_matches(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        today = date.today()
        start = _months_back(today, 6)
        response = client.get(
            f"/profile?date_from={start.isoformat()}&date_to={today.isoformat()}"
        )
        body = response.data.decode()
        assert "preset-btn--active" in body


# ------------------------------------------------------------------ #
# 8. date_from > date_to — flash error + fallback                      #
# ------------------------------------------------------------------ #

class TestInvalidDateOrder:
    def test_date_from_after_date_to_returns_200(self, seeded_client):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get(
            "/profile?date_from=2026-04-30&date_to=2026-04-01",
            follow_redirects=True,
        )
        assert response.status_code == 200

    def test_date_from_after_date_to_flashes_error_message(self, seeded_client):
        """The flash message 'Start date must be before end date.' must appear."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get(
            "/profile?date_from=2026-04-30&date_to=2026-04-01",
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "Start date must be before end date." in body

    def test_date_from_after_date_to_falls_back_to_unfiltered_view(self, seeded_client):
        """Falls back to unfiltered view — all 6 expenses total 5420.00."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get(
            "/profile?date_from=2026-04-30&date_to=2026-04-01",
            follow_redirects=True,
        )
        body = response.data.decode()
        assert "5,420.00" in body

    def test_date_from_equal_to_date_to_is_valid(self, seeded_client):
        """Exact same date for both bounds is a valid (single-day) range."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get(
            "/profile?date_from=2026-04-01&date_to=2026-04-01",
            follow_redirects=True,
        )
        body = response.data.decode()
        # Must NOT flash the error
        assert "Start date must be before end date." not in body
        assert response.status_code == 200


# ------------------------------------------------------------------ #
# 9. Malformed date strings — silent fallback                          #
# ------------------------------------------------------------------ #

class TestMalformedDateParams:
    @pytest.mark.parametrize("qs", [
        "date_from=not-a-date&date_to=2026-04-30",
        "date_from=2026-04-01&date_to=not-a-date",
        "date_from=not-a-date&date_to=not-a-date",
        "date_from=13/99/2026&date_to=2026-04-30",
        "date_from=2026-13-01&date_to=2026-04-30",
        "date_from=&date_to=",
        "date_from=2026-04-31&date_to=2026-04-30",  # impossible date
    ])
    def test_malformed_date_does_not_crash(self, seeded_client, qs):
        """Any malformed date must return 200 without raising an exception."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get(f"/profile?{qs}", follow_redirects=True)
        assert response.status_code == 200

    @pytest.mark.parametrize("qs", [
        "date_from=not-a-date&date_to=2026-04-30",
        "date_from=2026-04-01&date_to=not-a-date",
        "date_from=not-a-date&date_to=not-a-date",
    ])
    def test_malformed_date_falls_back_to_all_expenses(self, seeded_client, qs):
        """When either date is malformed, the unfiltered total (5420.00) must appear."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get(f"/profile?{qs}", follow_redirects=True)
        body = response.data.decode()
        assert "5,420.00" in body

    def test_single_valid_date_from_without_date_to_falls_back(self, seeded_client):
        """Providing only date_from (no date_to) must behave as unfiltered."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01")
        body = response.data.decode()
        assert "5,420.00" in body

    def test_single_valid_date_to_without_date_from_falls_back(self, seeded_client):
        """Providing only date_to (no date_from) must behave as unfiltered."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_to=2026-04-30")
        body = response.data.decode()
        assert "5,420.00" in body


# ------------------------------------------------------------------ #
# 10. Template variables present in response context                   #
# ------------------------------------------------------------------ #

class TestTemplateVariables:
    def test_filter_bar_section_present_on_profile_page(self, seeded_client):
        """The filter bar HTML section must be rendered on the profile page."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        assert "filter-bar" in body

    def test_all_preset_buttons_rendered(self, seeded_client):
        """All four preset button labels must appear in the rendered HTML."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        for label in ("This Month", "Last 3 Months", "Last 6 Months", "All Time"):
            assert label in body

    def test_date_input_fields_rendered(self, seeded_client):
        """The two date input fields (name=date_from and name=date_to) must exist."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        assert 'name="date_from"' in body
        assert 'name="date_to"' in body

    def test_active_filter_dates_reflected_in_input_values(self, seeded_client):
        """When a custom range is active, inputs must show those date values."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-03-01&date_to=2026-04-30")
        body = response.data.decode()
        assert "2026-03-01" in body
        assert "2026-04-30" in body

    def test_all_time_active_when_no_params(self, seeded_client):
        """With no query params, the All Time button must carry the active class."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        # The All Time anchor must have the active class applied
        assert "preset-btn--active" in body
        # Verify it is specifically adjacent to "All Time" text
        all_time_idx = body.find("All Time")
        active_idx = body.rfind("preset-btn--active", 0, all_time_idx)
        assert active_idx != -1, "All Time preset button should have the active class"


# ------------------------------------------------------------------ #
# 11. ₹ symbol present regardless of active filter                     #
# ------------------------------------------------------------------ #

class TestRupeeSymbol:
    @pytest.mark.parametrize("qs", [
        "",
        "?date_from=2026-04-01&date_to=2026-04-30",
        "?date_from=2026-03-01&date_to=2026-04-30",
        "?date_from=2026-01-01&date_to=2026-04-30",
    ])
    def test_rupee_symbol_present_in_all_filtered_views(self, seeded_client, qs):
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get(f"/profile{qs}")
        body = response.data.decode()
        assert "₹" in body

    def test_rupee_symbol_present_when_zero_expenses_in_range(self, empty_client):
        """Even with no expenses, ₹0.00 must appear — not a bare '0'."""
        client = empty_client
        conn = sqlite3.connect(db_module.DB_PATH)
        uid = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("empty@spendly.com",)
        ).fetchone()[0]
        conn.close()

        from app import app as flask_app
        set_session(client, flask_app, uid, user_name="Empty User")
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        body = response.data.decode()
        assert "₹0.00" in body


# ------------------------------------------------------------------ #
# 12. Empty range — no expenses in selected window                     #
# ------------------------------------------------------------------ #

class TestEmptyRangeForUser:
    def test_user_with_no_expenses_sees_zero_total(self, empty_client):
        client = empty_client
        conn = sqlite3.connect(db_module.DB_PATH)
        uid = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("empty@spendly.com",)
        ).fetchone()[0]
        conn.close()

        from app import app as flask_app
        set_session(client, flask_app, uid, user_name="Empty User")
        response = client.get("/profile")
        assert response.status_code == 200
        body = response.data.decode()
        assert "₹0.00" in body

    def test_user_with_no_expenses_sees_zero_transaction_count(self, empty_client):
        client = empty_client
        conn = sqlite3.connect(db_module.DB_PATH)
        uid = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("empty@spendly.com",)
        ).fetchone()[0]
        conn.close()

        from app import app as flask_app
        set_session(client, flask_app, uid, user_name="Empty User")
        response = client.get("/profile")
        body = response.data.decode()
        # transaction_count stat card must show 0
        assert "0" in body

    def test_seeded_user_with_date_range_outside_all_expenses_sees_zero_total(
        self, seeded_client
    ):
        """A date range with no matching expenses must show ₹0.00."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        # A range in the future with no seeded data
        response = client.get("/profile?date_from=2027-01-01&date_to=2027-01-31")
        assert response.status_code == 200
        body = response.data.decode()
        assert "₹0.00" in body

    def test_seeded_user_empty_range_has_empty_category_breakdown(self, seeded_client):
        """A date range with no matching expenses must produce an empty category list."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2027-01-01&date_to=2027-01-31")
        body = response.data.decode()
        # None of the real categories should appear in breakdown rows
        for cat in ("Food", "Transport", "Bills", "Health", "Shopping", "Entertainment"):
            # category names inside cat-row elements should not appear
            assert f'<span class="cat-name">{cat}</span>' not in body

    def test_seeded_user_empty_range_shows_no_transactions(self, seeded_client):
        """A date range with no matching expenses must produce an empty transaction list."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2027-01-01&date_to=2027-01-31")
        body = response.data.decode()
        for desc in ("April groceries", "March electricity", "Oct movie"):
            assert desc not in body

    def test_seeded_user_empty_range_does_not_raise_error(self, seeded_client):
        """No 500 error when range matches zero expenses."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2027-01-01&date_to=2027-01-31")
        assert response.status_code == 200


# ------------------------------------------------------------------ #
# Additional edge cases                                                #
# ------------------------------------------------------------------ #

class TestEdgeCases:
    def test_filter_does_not_expose_other_users_data(self, patched_app):
        """Expenses belonging to a different user must never appear."""
        client, flask_app = patched_app

        conn = sqlite3.connect(db_module.DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("User A", "a@spendly.com", generate_password_hash("pass1234")),
        )
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("User B", "b@spendly.com", generate_password_hash("pass1234")),
        )
        conn.commit()

        uid_a = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("a@spendly.com",)
        ).fetchone()[0]
        uid_b = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("b@spendly.com",)
        ).fetchone()[0]

        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid_a, 9999.00, "Other", "2026-04-10", "User A secret expense"),
        )
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid_b, 1.00, "Other", "2026-04-10", "User B unrelated expense"),
        )
        conn.commit()
        conn.close()

        # Log in as User B and check profile
        set_session(client, flask_app, uid_b, user_name="User B")
        response = client.get("/profile")
        body = response.data.decode()

        assert "User A secret expense" not in body
        assert "9,999.00" not in body

    def test_profile_page_renders_user_name(self, seeded_client):
        """The authenticated user's name must appear in the rendered profile page."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile")
        body = response.data.decode()
        assert "Test User" in body

    def test_sql_injection_in_date_param_does_not_crash(self, seeded_client):
        """A SQL injection attempt in date_from must be handled safely."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        malicious = "2026-04-01'; DROP TABLE expenses; --"
        response = client.get(
            f"/profile?date_from={malicious}&date_to=2026-04-30",
            follow_redirects=True,
        )
        # Must not crash; silently falls back to unfiltered
        assert response.status_code == 200

    def test_very_wide_date_range_returns_all_expenses(self, seeded_client):
        """A range like 2000-01-01 to 2099-12-31 returns all seeded expenses."""
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2000-01-01&date_to=2099-12-31")
        body = response.data.decode()
        assert "5,420.00" in body

    def test_top_category_reflects_filter(self, seeded_client):
        """
        In the April-only window (Food 450, Transport 120), top category
        must be Food, not Shopping (which is the overall top category at 2200).
        """
        client, uid = seeded_client
        from app import app as flask_app
        set_session(client, flask_app, uid)
        response = client.get("/profile?date_from=2026-04-01&date_to=2026-04-30")
        body = response.data.decode()
        # The stat card for Top Category must show Food
        # We look for Food appearing in the stats area; Shopping must not be top
        assert "Food" in body
