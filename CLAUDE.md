# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Spendly** — a personal expense tracker web app built with Flask and SQLite. Currency is Indian Rupees (₹). This is a step-by-step student learning project; many routes and the database layer are stubs to be implemented incrementally.

## Commands

```bash
# Run the dev server (port 5001, debug mode)
python app.py

# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run a single test file
pytest tests/test_auth.py

# Run a single test by name
pytest -k "test_login"
```

## Architecture

**`app.py`** — the entire Flask app lives here: app creation and all route handlers. Routes call into `database/db.py` for data access and render Jinja2 templates.

**`database/db.py`** — the SQLite data layer (currently a stub). Must implement:
- `get_db()` — returns a `sqlite3.Connection` with `row_factory = sqlite3.Row` and `PRAGMA foreign_keys = ON`
- `init_db()` — creates all tables using `CREATE TABLE IF NOT EXISTS`
- `seed_db()` — inserts sample data for development

**`templates/`** — Jinja2 templates. `base.html` is the master layout (navbar, footer, CSS/JS links); all page templates extend it via `{% block content %}`. The navbar currently only has Sign in / Get started links — it will need to change once auth is implemented to show logged-in state.

**`static/css/style.css`** — fully implemented design system using CSS custom properties (`:root` variables for colors, typography, spacing). `static/css/landing.css` handles the landing page specifically. `static/js/main.js` is a stub.

## Implemented vs. Stub Routes

| Route | Status |
|---|---|
| `/`, `/register`, `/login`, `/terms`, `/privacy` | Renders template |
| `/logout` | Stub — Step 3 |
| `/profile` | Stub — Step 4 |
| `/expenses/add` | Stub — Step 7 |
| `/expenses/<id>/edit` | Stub — Step 8 |
| `/expenses/<id>/delete` | Stub — Step 9 |
