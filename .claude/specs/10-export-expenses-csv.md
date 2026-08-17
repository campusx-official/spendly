# Spec: Export Expenses CSV

## Overview

Lets a logged-in user download their own expenses as a CSV file from the profile
page, honouring whatever date filter the profile is currently showing. All nine
roadmap steps are implemented and every existing route renders a template; this is
the first route in Spendly that returns a **file** rather than a template, which is
the deliberate exception here and not a new default. It exercises the full stack
without inventing a new layer — one query helper, one route, an ownership scope, one
template link, and tests — and needs no new pip package, since `csv` and `io` are
stdlib.

## Depends on

- Step 01 — database setup (`get_db()`, `expenses` schema)
- Step 03 — login/logout, so `session["user_id"]` exists
- Step 05 — backend routes for the profile page
- Step 06 — date filter on the profile page, which supplies `date_from` / `date_to`
  and the `_parse_date()` validator this route reuses
- Step 07 — add expense, so there are rows to export

## Routes

- `GET /expenses/export` — streams the current user's expenses as a CSV attachment;
  accepts optional `date_from` and `date_to` query args in `YYYY-MM-DD` — **logged-in**

No other routes change.

## Database changes

No database changes. Verified against `database/db.py` — the existing `expenses`
table (`id`, `user_id`, `amount`, `category`, `date`, `description`, `created_at`)
already holds everything the export needs. No new table, column, index, or
constraint.

## Templates

- **Create:** none
- **Modify:** `templates/profile.html` — add one export link inside the existing
  `<div class="filter-bar">`, after the closing `</form>` of the date-filter form
  (currently around line 53), using
  `{{ url_for('export_expenses', date_from=date_from, date_to=date_to) }}`.
  `date_from` and `date_to` are already in the template context, and `url_for`
  drops `None` args automatically, so an unfiltered profile produces a bare
  `/expenses/export`. Never hardcode the path.

## Files to change

| File | Change |
|---|---|
| `database/queries.py` | add `get_expenses_for_export(user_id, date_from=None, date_to=None)` |
| `app.py` | add `csv`, `io`, and Flask's `Response` to the imports; add the `export_expenses` route; import the new query helper |
| `templates/profile.html` | one export link in the filter bar |
| `static/css/profile.css` | style for the export link, next to `.filter-apply-btn` |
| `CLAUDE.md` | add `/expenses/export` to the Routes table; bump the test count |

## Files to create

- `tests/test_10_export_expenses_csv.py` — written by `/test-feature` from this spec,
  not from the implementation

## New dependencies

No new dependencies. `csv` and `io` are Python stdlib, so `requirements.txt` and
`requirements-prod.txt` stay untouched and the "no new pip packages" tech constraint
holds.

## Rules for implementation

- No SQLAlchemy or ORMs — raw `sqlite3` through `get_db()` only
- Parameterised queries only (`?` placeholders); never f-strings in SQL
- Passwords hashed with werkzeug (unchanged here — no auth code is touched)
- Use CSS variables — never hardcode hex values in `profile.css`
- All templates extend `base.html` (unchanged here — no new template)
- DB logic goes in `database/queries.py` for anything touching `expenses`, or
  `database/db.py` for connection, schema, and `users` work — never inline in a route
- Per-resource routes must enforce ownership the way `/expenses/<id>/edit` does:
  `get_expense_by_id(id, session["user_id"])` returning `None` then `abort(404)`.
  This route is not per-resource, so the equivalent is that **`user_id` is a required
  parameter of the query helper and every row is scoped by it in SQL** — never filter
  by user in Python, and never accept a `user_id` from the request.
- Auth guard must match the inlined pattern used by every protected route — there is
  no `@login_required` decorator:
  ```python
  if not session.get("user_id"):
      return redirect(url_for("login"))
  ```
- **Return raw values, not display strings.** Do not reuse
  `get_recent_transactions()`: it formats amounts as `"1,200.00"` (the thousands
  comma breaks CSV parsing) and dates as `"03 Apr 2026"`, and it carries a
  `limit=10` an export must not inherit. The CSV needs `1200.0` and `2026-04-03`.
  That is precisely why this is a new helper.
- Reuse the existing `_build_date_filter(date_from, date_to)` helper in
  `queries.py` so filtering behaves identically to the profile page. Note its
  documented behaviour: it applies `date BETWEEN ? AND ?` **only when both bounds
  are truthy**, and is a no-op otherwise. Do not "fix" that here — matching the
  profile is the requirement; a one-sided filter changing behaviour would make the
  export disagree with the table it sits next to.
- Order rows `ORDER BY date DESC, id DESC`, the same ordering the profile table uses
- Coerce a NULL `description` to `""` the way `get_expense_by_id()` does
  (`description or ""`), so the CSV never contains the literal text `None`
- Validate both date args through the existing `_parse_date()` in `app.py`; an
  invalid date becomes `None` (no filter) rather than an error
- Build the CSV with `csv.writer` into an `io.StringIO`, then return a `Response`
  with `Content-Type: text/csv` and a `Content-Disposition: attachment; filename=...`
  header. Do not write a temp file to disk.
- Route function must be one responsibility — fetch, serialise, return. No query
  building in the route.
- Name the view function `export_expenses`, since the template link and tests
  reference it by that endpoint name

## Definition of done

Verifiable by running the app on port 5001 and by `pytest`:

1. `GET /expenses/export` while logged out returns a **302 redirect to `/login`** and
   no CSV body.
2. `GET /expenses/export` while logged in returns **200** with
   `Content-Type` containing `text/csv` and a `Content-Disposition: attachment`
   header carrying a `.csv` filename.
3. The first line of the body is a header row naming the columns
   (date, category, amount, description).
4. Amounts appear as plain numbers (`1200.0` / `1200.00`) with **no thousands
   comma**, and dates appear in ISO `YYYY-MM-DD` — not `"1,200.00"` / `"03 Apr 2026"`.
5. A user with more than 10 expenses gets **all** of them, proving the `limit=10`
   of `get_recent_transactions()` was not inherited.
6. User A's export contains **none** of user B's rows, verified with two seeded users.
7. `GET /expenses/export?date_from=2026-04-01&date_to=2026-04-03` returns only rows
   inside that range, and the same range on `/profile` shows the same set.
8. Passing only `date_from` (no `date_to`) returns all rows — matching the profile's
   existing behaviour — and does not error.
9. `GET /expenses/export?date_from=not-a-date` returns 200 with all rows, not a 500.
10. An expense saved with an empty description produces an empty CSV field, not the
    text `None`.
11. A user with zero expenses gets a 200 with the header row only.
12. The profile page renders an export link whose `href` carries the currently
    active `date_from` / `date_to`, and is absent of any hardcoded `/expenses/export`
    string in the template source (`url_for` only).
13. `pytest` is fully green.
14. `python .claude/verify_setup.py` passes — it checks the new route appears in
    `CLAUDE.md`'s Routes table in both directions.
