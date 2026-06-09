from datetime import datetime

from database.db import get_db


def _date_clause(date_from, date_to):
    if date_from and date_to:
        return " AND date BETWEEN ? AND ?", (date_from, date_to)
    return "", ()


def get_user_by_id(user_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        created_at = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        words = row["name"].split()
        initials = "".join(w[0].upper() for w in words if w)[:2]
        return {
            "name": row["name"],
            "email": row["email"],
            "member_since": created_at.strftime("%B %Y"),
            "initials": initials,
        }
    finally:
        db.close()


def get_summary_stats(user_id, date_from=None, date_to=None):
    db = get_db()
    date_sql, date_params = _date_clause(date_from, date_to)
    try:
        row = db.execute(
            "SELECT SUM(amount) AS total_spent, COUNT(*) AS transaction_count "
            "FROM expenses WHERE user_id = ?" + date_sql,
            (user_id, *date_params),
        ).fetchone()
        total_spent = row["total_spent"] if row["total_spent"] is not None else 0
        transaction_count = int(row["transaction_count"])
        if transaction_count == 0:
            return {"total_spent": "₹0.00", "transaction_count": 0, "top_category": "—"}
        cat_row = db.execute(
            "SELECT category FROM expenses WHERE user_id = ?" + date_sql +
            " GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            (user_id, *date_params),
        ).fetchone()
        return {
            "total_spent": "₹{:,.2f}".format(total_spent),
            "transaction_count": transaction_count,
            "top_category": cat_row["category"] if cat_row else "—",
        }
    finally:
        db.close()


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    db = get_db()
    date_sql, date_params = _date_clause(date_from, date_to)
    try:
        rows = db.execute(
            "SELECT id, date, description, category, amount "
            "FROM expenses WHERE user_id = ?" + date_sql +
            " ORDER BY date DESC LIMIT ?",
            (user_id, *date_params, limit),
        ).fetchall()
        result = []
        for row in rows:
            parsed = datetime.strptime(row["date"], "%Y-%m-%d")
            formatted_date = "{} {} {}".format(
                parsed.day, parsed.strftime("%b"), parsed.strftime("%Y")
            )
            result.append({
                "id": row["id"],
                "date": formatted_date,
                "description": row["description"],
                "category": row["category"],
                "amount": "₹{:,.2f}".format(row["amount"]),
            })
        return result
    finally:
        db.close()


def get_category_breakdown(user_id, date_from=None, date_to=None):
    db = get_db()
    date_sql, date_params = _date_clause(date_from, date_to)
    try:
        rows = db.execute(
            "SELECT category, SUM(amount) AS total "
            "FROM expenses WHERE user_id = ?" + date_sql +
            " GROUP BY category ORDER BY total DESC",
            (user_id, *date_params),
        ).fetchall()
        if not rows:
            return []
        grand_total = sum(r["total"] for r in rows)
        if grand_total == 0:
            return []
        result = [
            {
                "name": r["category"],
                "amount": "₹{:,.2f}".format(r["total"]),
                "percent": round(r["total"] / grand_total * 100),
            }
            for r in rows
        ]
        remainder = 100 - sum(item["percent"] for item in result)
        if remainder != 0:
            result[0]["percent"] += remainder
        return result
    finally:
        db.close()
