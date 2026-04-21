# Spec: Login and Logout

## Overview
Implement login and logout so registered users can authenticate and maintain a session across requests. This step wires up the `/login` route to accept POST data, verify credentials against the `users` table, store the user's id and name in Flask's signed session cookie, and redirect to a dashboard stub. The `/logout` route clears the session and returns the user to the landing page. It also updates the navbar in `base.html` to show either Sign in / Get started (logged-out) or the user's name and a Logout link (logged-in).

## Depends on
- Step 1 — Database Setup (`users` table must exist, `get_db()` must work)
- Step 2 — Registration (a user row must exist to log in with)

## Routes
- `GET  /login` — renders the login form — public
- `POST /login` — validates credentials, sets session, redirects to `/dashboard` — public
- `GET  /logout` — clears the session, redirects to `/` — logged-in

## Database changes
No database changes. The existing `users` table (id, name, email, password_hash, created_at) is sufficient.

## Templates
- **Modify:** `templates/login.html`
  - Convert the static form to post to `POST /login`
  - Add a `{{ get_flashed_messages() }}` block to display errors
- **Modify:** `templates/base.html`
  - Update the navbar: if `session.user_id` is set, show the user's name and a Logout link; otherwise show Sign in / Get started links
- **Create:** `templates/dashboard.html`
  - Minimal placeholder page extending `base.html` with a heading "Dashboard — coming soon"

## Files to change
- `app.py` — add `POST` method to `/login` route with credential check, session write, and redirect; implement `/logout` to clear session and redirect; add a `/dashboard` stub route
- `templates/login.html` — wire up the form and flash messages
- `templates/base.html` — conditional navbar based on session state

## Files to create
- `templates/dashboard.html` — minimal logged-in landing stub

## New dependencies
No new dependencies. `werkzeug.security.check_password_hash` and `flask.session` are already available.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use string formatting in SQL
- Verify passwords with `werkzeug.security.check_password_hash` — never compare plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Store only `user_id` and `user_name` in the session — never store the password hash or full user row
- The `/logout` route must call `session.clear()` (or `session.pop`) and then redirect — never just redirect
- Flash a generic error ("Invalid email or password") for both wrong email and wrong password — do not distinguish which field failed
- After successful login redirect to `/dashboard`
- Add a `login_required` check to `/dashboard` (redirect to `/login` if not logged in) as a pattern for future protected routes

## Definition of done
- [ ] `GET /login` renders the form without errors
- [ ] Submitting with a wrong email or wrong password shows "Invalid email or password" and re-renders the form
- [ ] Submitting valid credentials redirects to `/dashboard`
- [ ] After login, `session['user_id']` and `session['user_name']` are set
- [ ] The navbar shows the user's name and a Logout link when logged in
- [ ] The navbar shows Sign in / Get started links when logged out
- [ ] `GET /logout` clears the session and redirects to `/`
- [ ] After logout the navbar reverts to the logged-out state
- [ ] Visiting `/dashboard` while logged out redirects to `/login`
