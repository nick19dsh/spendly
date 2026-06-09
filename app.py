import re
import sqlite3
from datetime import date, datetime
# Pre-load _strptime to prevent Werkzeug's reloader from treating its lazy import as a file
# change mid-request and restarting the server. See https://bugs.python.org/issue7980
datetime.strptime("2000-01-01", "%Y-%m-%d")

from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import get_db, init_db, seed_db, insert_user, get_user_by_email, insert_expense, get_expense_by_id, update_expense
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)

app = Flask(__name__)
app.secret_key = "spendly-dev-secret"


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        if "user_id" in session:
            return redirect(url_for("profile"))
        return render_template("register.html")

    name     = request.form.get("name", "").strip()
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not name:
        flash("Full name is required.", "error")
        return render_template("register.html")
    if not email:
        flash("Email address is required.", "error")
        return render_template("register.html")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        flash("Please enter a valid email address.", "error")
        return render_template("register.html")
    if not password:
        flash("Password is required.", "error")
        return render_template("register.html")
    if len(password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return render_template("register.html")

    try:
        insert_user(name, email, generate_password_hash(password))
    except sqlite3.IntegrityError:
        flash("An account with that email already exists.", "error")
        return render_template("register.html")

    flash("Account created — please log in", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "user_id" in session:
            return redirect(url_for("profile"))
        return render_template("login.html")

    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        flash("Invalid email or password.", "error")
        return render_template("login.html")

    session.clear()
    session["user_id"]   = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html")


def _parse_date(val):
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _build_date_presets(today):
    first_of_month = today.replace(day=1)
    three_months_ago = date(
        today.year if today.month > 3 else today.year - 1,
        (today.month - 3) % 12 or 12,
        1,
    )
    six_months_ago = date(
        today.year if today.month > 6 else today.year - 1,
        (today.month - 6) % 12 or 12,
        1,
    )
    return {
        "this_month":    {"date_from": first_of_month.isoformat(),   "date_to": today.isoformat()},
        "last_3_months": {"date_from": three_months_ago.isoformat(), "date_to": today.isoformat()},
        "last_6_months": {"date_from": six_months_ago.isoformat(),   "date_to": today.isoformat()},
    }


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    uid = session["user_id"]
    user = get_user_by_id(uid)

    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))

    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        date_from = date_to = None

    date_from_str = date_from.isoformat() if date_from else None
    date_to_str = date_to.isoformat() if date_to else None

    stats = get_summary_stats(uid, date_from=date_from_str, date_to=date_to_str)
    transactions = get_recent_transactions(uid, date_from=date_from_str, date_to=date_to_str)
    categories = get_category_breakdown(uid, date_from=date_from_str, date_to=date_to_str)

    return render_template("profile.html",
                           user=user, stats=stats,
                           transactions=transactions, categories=categories,
                           date_from=date_from_str, date_to=date_to_str,
                           presets=_build_date_presets(date.today()))


@app.route("/analytics")
def analytics():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("analytics.html")


EXPENSE_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


def _validate_expense_form(amount_raw, category, expense_date, description):
    """Returns (amount_float, None) on success, or (None, error_message) on failure."""
    try:
        amount = float(amount_raw)
        if amount <= 0 or amount > 1_000_000:
            raise ValueError
    except ValueError:
        return None, "Amount must be a number between ₹0.01 and ₹10,00,000."

    if category not in EXPENSE_CATEGORIES:
        return None, "Please select a valid category."

    if not expense_date:
        return None, "Date is required."
    try:
        datetime.strptime(expense_date, "%Y-%m-%d")
    except ValueError:
        return None, "Date must be in YYYY-MM-DD format."

    if description and len(description) > 200:
        return None, "Description must be 200 characters or fewer."

    return amount, None


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("add_expense.html",
                               categories=EXPENSE_CATEGORIES,
                               today=date.today().isoformat())

    amount_raw   = request.form.get("amount", "").strip()
    category     = request.form.get("category", "").strip()
    expense_date = request.form.get("date", "").strip()
    description  = request.form.get("description", "").strip()

    amount, error = _validate_expense_form(amount_raw, category, expense_date, description)
    if error:
        flash(error, "error")
        return render_template("add_expense.html", categories=EXPENSE_CATEGORIES,
                               amount=amount_raw, category=category,
                               expense_date=expense_date, description=description,
                               today=date.today().isoformat())

    insert_expense(session["user_id"], amount, category, expense_date, description or None)
    flash("Expense added.", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    expense = get_expense_by_id(id)
    if expense is None:
        abort(404)
    if expense["user_id"] != session["user_id"]:
        abort(403)

    if request.method == "GET":
        return render_template("edit_expense.html",
                               categories=EXPENSE_CATEGORIES,
                               amount=expense["amount"],
                               category=expense["category"],
                               expense_date=expense["date"],
                               description=expense["description"] or "",
                               expense_id=id)

    amount_raw   = request.form.get("amount", "").strip()
    category     = request.form.get("category", "").strip()
    expense_date = request.form.get("date", "").strip()
    description  = request.form.get("description", "").strip()

    amount, error = _validate_expense_form(amount_raw, category, expense_date, description)
    if error:
        flash(error, "error")
        return render_template("edit_expense.html", categories=EXPENSE_CATEGORIES,
                               amount=amount_raw, category=category,
                               expense_date=expense_date, description=description,
                               expense_id=id)

    update_expense(id, session["user_id"], amount, category, expense_date, description or None)
    flash("Expense updated.", "success")
    return redirect(url_for("profile"))


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


with app.app_context():
    init_db()
    seed_db()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
