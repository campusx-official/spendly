# Spec: Bangladesh Localization

## Overview
Spendly currently displays money with a hardcoded ₹ (Indian Rupee) symbol baked
directly into `profile.html`, and formats amounts with Western thousands-grouping
(`"{:,.2f}"`) inside three `database/queries.py` helpers. This step swaps the
displayed currency to ৳ (Bangladeshi Taka) and switches amount grouping to the
Bangladeshi/South Asian lakh–crore convention (e.g. `1,00,000.00` instead of
`100,000.00`). This is a **global default display change**, not a per-user
preference — the app has no locale/currency/language infrastructure today (no
`users` column for it, no settings route, no translation layer), and building
that is explicitly out of scope for this spec. Anything beyond currency symbol
and digit grouping (UI text translation, timezone handling, a user-facing
language switch) is a separate, much larger feature and is not attempted here.

## Depends on
- Step 01 (database setup) — `expenses.amount` column this formats
- Step 05 (backend routes for profile page) — introduces
  `get_recent_transactions()`, `get_summary_stats()`, `get_category_breakdown()`,
  the three functions this step modifies
- Step 10 (CSV export) — `get_expenses_for_export()` must remain unaffected;
  this step must not regress the raw-value contract that export depends on

## Routes
No new routes.

## Database changes
No database changes. No new column, no new table, no per-user setting.

## Templates
- **Create:** none
- **Modify:** `templates/profile.html` — replace the hardcoded `₹` glyph with
  `৳` in all three places it appears: the total stat (`stat-value`), the
  transaction table (`tx-amount`), and the category breakdown
  (`cat-row-amount`)

## Files to change
- `database/queries.py`
  - Add a private helper, e.g. `_format_bdt_amount(amount)`, that formats a
    float to 2 decimal places using lakh–crore digit grouping (group the last
    3 digits, then group the remainder in pairs of 2 from the right — e.g.
    `1234567.89` → `"12,34,567.89"`, `2450.0` → `"2,450.00"` unchanged from
    today since grouping is identical below 100,000).
  - Replace the three separate `"{:,.2f}".format(...)` call sites in
    `get_recent_transactions()`, `get_summary_stats()`, and
    `get_category_breakdown()` with calls to this one shared helper, so the
    grouping logic exists in exactly one place.
- `templates/profile.html` — swap `₹` → `৳` in the three spots above.
- `tests/test_06_date_filter_profile.py` — this pre-existing file asserts
  `"₹" in body` in **four** places. These are step 06's tests, not step 11's,
  but the currency swap invalidates them directly. Update all four to check
  for `"৳"` instead. This is a deliberate, explicit exception to "tests come
  from the spec, not the implementation" — call it out during `/test-feature`
  rather than letting it appear as an unexplained diff to an unrelated spec's
  test file.

## Files to create
None.

## New dependencies
No new dependencies. No `Flask-Babel`, no locale/ICU package — the lakh–crore
grouping is implemented as a small pure-Python function, and the currency
symbol is a static character, so no new pip package is needed.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- DB logic goes in `database/queries.py` for anything touching `expenses`, or
  `database/db.py` for connection, schema, and `users` work — never inline in
  a route (this feature touches `queries.py` only; no route or `db.py` change)
- Per-resource routes must enforce ownership the way `/expenses/<id>/edit`
  does — not applicable here, no route is added or modified
- `_format_bdt_amount()` is a **display-only** formatter. `get_expenses_for_export()`
  must keep returning raw, unformatted floats and ISO date strings, exactly as
  step 10 established — do not call the new formatter from that function, and
  do not let CSV output change in any way
- Amounts under ৳1,00,000 must render byte-for-byte identically to today's
  Western-grouped output (the two conventions agree below the lakh threshold)
  — this is a regression check, not just a new-behavior check
- `member_since`'s English month-name formatting (`queries.py`, via
  `strftime("%B %Y")`) is explicitly **out of scope** — do not touch it
- This is a global display default, not a per-user setting — do not add a
  `users` column, a settings route, or any per-request locale detection

## Definition of done
- [ ] `/profile` displays `৳` (not `₹`) in the total stat, every transaction
      row, and every category breakdown row
- [ ] Seed or add an expense whose amount is ≥ 100,000 and confirm it renders
      with lakh–crore grouping, e.g. `100000.0` → `৳1,00,000.00`
- [ ] Confirm an amount under 100,000 (e.g. `2450.0`) still renders exactly as
      `2,450.00` — unchanged from before this change
- [ ] `GET /expenses/export` still returns raw, unformatted amounts and dates
      (re-run `tests/test_10_export_expenses_csv.py` — must still pass
      unmodified)
- [ ] `member_since` on `/profile` still renders an English month name,
      unchanged
- [ ] `tests/test_06_date_filter_profile.py`'s four `"₹" in body` assertions
      are updated to `"৳"` and the file passes
- [ ] Full suite passes: `pytest`
- [ ] `python .claude/verify_setup.py` still passes (sanity check — no route
      or schema change is expected in this step)
