# Spec: Registration

## Overview
Implement user registration so new visitors can create a Spendly account. This step wires up the `/register` route (currently a stub that only renders the template) to accept POST data, validate inputs, hash the password, insert a new row into the `users` table, and redirect the user on success. It also adds flash-message support so form errors and confirmations surface in the UI.

## Depends on
- Step 1 — Database Setup (`users` table must exist, `get_db()` must work)

## Routes
- `GET  /register` — renders the registration form — public
- `POST /register` — validates form data, creates the user, redirects to `/login` — public

## Database changes
No new tables or columns. The existing `users` table (id, name, email, password_hash, created_at) is sufficient.

## Templates
- **Modify:** `templates/register.html`
  - Convert the static form to post to `POST /register`
  - Add a `{{ get_flashed_messages() }}` block to display validation errors and success messages
  - Show field-level errors next to each input when present

## Files to change
- `app.py` — add `POST` method to the `/register` route; add form validation, duplicate-email check, password hashing, `db.insert_user()` call, flash messages, and redirects; add `SECRET_KEY` to app config
- `database/db.py` — add `insert_user(name, email, password)` function
- `templates/register.html` — wire up the form and flash messages

## Files to create
No new files.

## New dependencies
No new dependencies. `werkzeug.security` and `flask` (flash, redirect, url_for, request, session) are already available.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use string formatting in SQL
- Hash passwords with `werkzeug.security.generate_password_hash` — never store plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `app.secret_key` must be set (use `os.urandom(24)` or a hardcoded dev string) before `flash()` works
- Validate all three fields (name, email, password) server-side; return errors via `flash()`
- Catch the `UNIQUE constraint failed` error on duplicate email and flash a user-friendly message
- After successful registration, redirect to `/login` with a success flash message
- Do not log the user in automatically — that belongs in Step 3

## Definition of done
- [ ] `GET /register` renders the form without errors
- [ ] Submitting empty fields re-renders the form with a flash error for each missing field
- [ ] Submitting a duplicate email shows "An account with that email already exists" (or similar)
- [ ] Submitting valid data inserts a new row into `users` with a hashed password
- [ ] After successful registration the user is redirected to `/login`
- [ ] A success flash message ("Account created — please log in") is visible on the login page
- [ ] The plaintext password is never stored in the database
- [ ] Registering twice with the same email is rejected
