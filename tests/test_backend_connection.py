import os
import sqlite3
import pytest
from werkzeug.security import generate_password_hash

os.environ["SPENDLY_TEST_DB"] = ":memory:"

import database.db as db_module
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    """Point every get_db() call at a fresh in-memory database."""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_file)

    conn = db_module.get_db()
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


@pytest.fixture
def user_with_expenses(patch_db):
    conn = db_module.get_db()
    conn.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Demo User", "demo@spendly.com", generate_password_hash("demo123"), "2026-01-15 10:30:00"),
    )
    conn.commit()
    uid = conn.execute("SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)).fetchone()[0]
    expenses = [
        (uid, 450.00,  "Food",          "2026-04-01", "Groceries"),
        (uid, 120.00,  "Transport",     "2026-04-03", "Auto ride"),
        (uid, 1500.00, "Bills",         "2026-04-05", "Electricity bill"),
        (uid, 800.00,  "Health",        "2026-04-08", "Pharmacy"),
        (uid, 350.00,  "Entertainment", "2026-04-10", "Movie tickets"),
        (uid, 2200.00, "Shopping",      "2026-04-12", "Clothes"),
        (uid, 60.00,   "Other",         "2026-04-15", "Miscellaneous"),
        (uid, 300.00,  "Food",          "2026-04-17", "Restaurant dinner"),
    ]
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        expenses,
    )
    conn.commit()
    conn.close()
    return uid


@pytest.fixture
def user_no_expenses(patch_db):
    conn = db_module.get_db()
    conn.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("New User", "new@spendly.com", generate_password_hash("password1"), "2026-04-01 09:00:00"),
    )
    conn.commit()
    uid = conn.execute("SELECT id FROM users WHERE email = ?", ("new@spendly.com",)).fetchone()[0]
    conn.close()
    return uid


# ------------------------------------------------------------------ #
# get_user_by_id                                                      #
# ------------------------------------------------------------------ #

def test_get_user_by_id_valid(user_with_expenses):
    result = get_user_by_id(user_with_expenses)
    assert result["name"] == "Demo User"
    assert result["email"] == "demo@spendly.com"
    assert result["member_since"] == "January 2026"
    assert result["initials"] == "DU"


def test_get_user_by_id_nonexistent(patch_db):
    assert get_user_by_id(9999) is None


# ------------------------------------------------------------------ #
# get_summary_stats                                                   #
# ------------------------------------------------------------------ #

def test_get_summary_stats_with_expenses(user_with_expenses):
    stats = get_summary_stats(user_with_expenses)
    assert stats["transaction_count"] == 8
    assert stats["total_spent"] == "₹5,780.00"
    assert stats["top_category"] == "Shopping"


def test_get_summary_stats_no_expenses(user_no_expenses):
    stats = get_summary_stats(user_no_expenses)
    assert stats == {"total_spent": "₹0.00", "transaction_count": 0, "top_category": "—"}


# ------------------------------------------------------------------ #
# get_recent_transactions                                             #
# ------------------------------------------------------------------ #

def test_get_recent_transactions_with_expenses(user_with_expenses):
    txs = get_recent_transactions(user_with_expenses)
    assert len(txs) == 8
    for tx in txs:
        assert "date" in tx
        assert "description" in tx
        assert "category" in tx
        assert tx["amount"].startswith("₹")
    # newest-first: 2026-04-17 should be first
    assert txs[0]["description"] == "Restaurant dinner"


def test_get_recent_transactions_no_expenses(user_no_expenses):
    assert get_recent_transactions(user_no_expenses) == []


def test_get_recent_transactions_limit(user_with_expenses):
    txs = get_recent_transactions(user_with_expenses, limit=3)
    assert len(txs) == 3


# ------------------------------------------------------------------ #
# get_category_breakdown                                              #
# ------------------------------------------------------------------ #

def test_get_category_breakdown_with_expenses(user_with_expenses):
    breakdown = get_category_breakdown(user_with_expenses)
    assert len(breakdown) == 7
    names = [c["name"] for c in breakdown]
    assert "Food" in names
    assert "Shopping" in names
    # ordered by amount desc — Shopping (2200) should be first
    assert breakdown[0]["name"] == "Shopping"
    # pct values sum to 100
    assert sum(c["percent"] for c in breakdown) == 100
    for cat in breakdown:
        assert cat["amount"].startswith("₹")
        assert isinstance(cat["percent"], int)


def test_get_category_breakdown_no_expenses(user_no_expenses):
    assert get_category_breakdown(user_no_expenses) == []


# ------------------------------------------------------------------ #
# Route tests                                                         #
# ------------------------------------------------------------------ #

@pytest.fixture
def app_client(patch_db):
    import app as flask_app
    flask_app.app.config["TESTING"] = True
    flask_app.app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.app.test_client() as client:
        yield client


def test_profile_unauthenticated(app_client):
    response = app_client.get("/profile")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_profile_authenticated(app_client, user_with_expenses):
    with app_client.session_transaction() as sess:
        sess["user_id"] = user_with_expenses
        sess["user_name"] = "Demo User"
    response = app_client.get("/profile")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "Demo User" in body
    assert "demo@spendly.com" in body
    assert "₹" in body
    assert "₹5,780.00" in body
    assert "Shopping" in body
