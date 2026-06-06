# Spec: Add Expense

## Overview
This feature implements the `/expenses/add` route, allowing logged-in users to submit a new expense entry via a form. The form collects amount, category, date, and an optional description, validates all inputs server-side, inserts the record into the `expenses` table, and redirects the user back to their profile with a success flash message. This is the first write operation in the Spendly workflow and the foundation that makes the dashboard and profile stats meaningful with real user data.

## Depends on
- Step 01 — Database Setup (expenses table must exist)
- Step 02 — Registration (users must exist)
- Step 03 — Login and Logout (session must be established)
- Step 05 — Backend Routes / Profile (profile page to redirect back to)

## Routes
- `GET /expenses/add` — renders the add expense form — logged-in only
- `POST /expenses/add` — processes form submission, inserts expense, redirects — logged-in only

## Database changes
No database changes. The `expenses` table already exists in `database/db.py` with columns: `id`, `user_id`, `amount`, `category`, `date`, `description`, `created_at`.

## Templates
- **Create:** `templates/add_expense.html` — form with fields for amount, category, date, description; extends `base.html`

## Files to change
- `app.py` — replace the stub `add_expense` route with a full GET/POST implementation
- `database/db.py` — add `insert_expense(user_id, amount, category, date, description)` helper
- `templates/base.html` — add "Add Expense" nav link visible to logged-in users (next to Analytics)

## Files to create
- `templates/add_expense.html` — the expense entry form template

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (not applicable here, but retain existing password handling)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Redirect to `/profile` after successful insert with `flash("Expense added.", "success")`
- On validation error, re-render the form with the error message and previously entered values pre-filled
- `amount` must be a positive number (> 0); reject non-numeric or zero/negative values
- `category` must be one of the fixed allowed values: Food, Transport, Bills, Health, Entertainment, Shopping, Other
- `date` must be a valid date in `YYYY-MM-DD` format; default the field to today's date
- `description` is optional (max 200 characters if provided)
- Unauthenticated requests to both GET and POST redirect to `/login`

## Definition of done
- [ ] `GET /expenses/add` renders the form when logged in
- [ ] `GET /expenses/add` redirects to `/login` when not logged in
- [ ] Submitting valid data inserts a row into the `expenses` table and redirects to `/profile` with a success flash
- [ ] Submitting an empty or non-numeric amount re-renders the form with an error
- [ ] Submitting amount ≤ 0 re-renders the form with an error
- [ ] Submitting an invalid or missing date re-renders the form with an error
- [ ] Submitting an invalid category re-renders the form with an error
- [ ] The form pre-fills submitted values when validation fails (amount, date, description)
- [ ] The new expense appears in the profile's Recent Transactions list after successful submission
- [ ] The "Add Expense" nav link is visible in the navbar only when logged in
