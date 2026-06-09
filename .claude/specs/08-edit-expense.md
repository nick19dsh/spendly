# Spec: Edit Expense

## Overview
This feature implements the `/expenses/<id>/edit` route, allowing logged-in users to edit an existing expense they own. The user clicks an edit button on a pre-filled form showing the existing expense values, makes changes, submits, and is redirected back to their profile with a success flash message. The route enforces ownership — a user may only edit their own expenses. This builds directly on the Add Expense step (07) and completes the full CRUD lifecycle for individual expenses.

## Depends on
- Step 01 — Database Setup (expenses table must exist)
- Step 02 — Registration (users must exist)
- Step 03 — Login and Logout (session must be established)
- Step 05 — Backend Routes / Profile (profile page to redirect back to)
- Step 07 — Add Expense (insert_expense DB helper, add_expense.html template as design reference, EXPENSE_CATEGORIES constant in app.py)

## Routes
- `GET /expenses/<int:id>/edit` — renders the edit form pre-filled with the existing expense values — logged-in only
- `POST /expenses/<int:id>/edit` — processes form submission, updates the expense row, redirects — logged-in only

## Database changes
No new tables or columns. A new DB helper `update_expense` and `get_expense_by_id` are needed in `database/db.py`.

- `get_expense_by_id(expense_id)` — fetches a single expense row by its `id`; returns `None` if not found
- `update_expense(expense_id, amount, category, expense_date, description)` — updates `amount`, `category`, `date`, and `description` for the given `id`

## Templates
- **Create:** `templates/edit_expense.html` — edit form pre-filled with existing values; same fields as `add_expense.html`; extends `base.html`
- **Modify:** `templates/profile.html` — add an Edit button/link next to each transaction row that links to `/expenses/<id>/edit`

## Files to change
- `app.py` — replace the stub `edit_expense` route with a full GET/POST implementation
- `database/db.py` — add `get_expense_by_id` and `update_expense` helpers
- `templates/profile.html` — add Edit link/button per transaction row

## Files to create
- `templates/edit_expense.html` — the edit expense form template

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (not applicable here, but retain existing password handling)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Redirect to `/profile` after a successful update with `flash("Expense updated.", "success")`
- On validation error, re-render the edit form with the error and the submitted (not original) values pre-filled
- Ownership check: after fetching the expense, verify `expense["user_id"] == session["user_id"]`; if not, abort with 403
- If the expense `id` does not exist, return a 404 response
- Unauthenticated requests to both GET and POST redirect to `/login`
- Validation rules are identical to Add Expense:
  - `amount` must be a positive number > 0 and ≤ 1,000,000
  - `category` must be one of the fixed allowed values: Food, Transport, Bills, Health, Entertainment, Shopping, Other
  - `date` must be a valid date in `YYYY-MM-DD` format
  - `description` is optional (max 200 characters if provided)
- Reuse the `EXPENSE_CATEGORIES` constant already defined in `app.py`

## Definition of done
- [ ] `GET /expenses/<id>/edit` renders the edit form pre-filled with the expense's current values when logged in as the owner
- [ ] `GET /expenses/<id>/edit` redirects to `/login` when not logged in
- [ ] `GET /expenses/<id>/edit` returns 403 when the expense belongs to a different user
- [ ] `GET /expenses/<id>/edit` returns 404 when the expense id does not exist
- [ ] Submitting valid data updates the expense row in the database and redirects to `/profile` with a success flash
- [ ] Submitting an empty or non-numeric amount re-renders the form with an error
- [ ] Submitting amount ≤ 0 or > 1,000,000 re-renders the form with an error
- [ ] Submitting an invalid or missing date re-renders the form with an error
- [ ] Submitting an invalid category re-renders the form with an error
- [ ] Description > 200 characters re-renders the form with an error
- [ ] The form pre-fills submitted values (not original values) when validation fails
- [ ] `POST /expenses/<id>/edit` returns 403 when the expense belongs to a different user
- [ ] The updated expense values are reflected in the profile's Recent Transactions list after a successful update
- [ ] Each transaction row on the profile page has a working Edit link that leads to the correct edit form
