# Spec: Delete Expense

## Overview
Step 9 lets a logged-in user permanently delete one of their own expenses directly
from the profile transaction table. A "Delete" button per row submits a POST request
to `/expenses/<id>/delete`; the handler verifies ownership, removes the row from
the database, and redirects back to `/profile`. There is no separate confirmation
page — a browser-side `confirm()` dialog in the button's `onclick` handler is used
to prevent accidental deletions. The existing `get_expense_by_id` helper (from Step 8)
is reused for ownership verification, so no new query lookup functions are needed —
only a new `delete_expense` mutation helper is added to `database/queries.py`.

## Depends on
- Step 1: Database setup (`expenses` table exists)
- Step 3: Login / Logout (`session["user_id"]` is set and enforced)
- Step 5: Profile page renders transactions (the delete button lives there)
- Step 8: Edit Expense (`get_expense_by_id` is available; Actions column already exists in profile)

## Routes
- `POST /expenses/<int:id>/delete` — verify ownership, delete the expense row, redirect to `/profile` — logged-in only

## Database changes
No new tables or columns. The `expenses` table already has all required columns.

## Templates
- **Modify**: `templates/profile.html`
  - Inside the existing "Actions" `<td>` per transaction row, add a delete form:
    ```html
    <form method="POST" action="/expenses/{{ tx.id }}/delete" style="display:inline"
          onsubmit="return confirm('Delete this expense?')">
      <button type="submit" class="btn-delete">Delete</button>
    </form>
    ```
  - Note: inline `style="display:inline"` is acceptable here only because it is a
    layout-utility value on a `<form>` tag, not a design value. No hex colours or
    design values may be inlined.

## Files to change
- `database/queries.py`
  - Add `delete_expense(expense_id, user_id)` — issues a parameterised
    `DELETE FROM expenses WHERE id = ? AND user_id = ?` to ensure ownership;
    commits and closes the connection.

- `app.py`
  - Import `delete_expense` from `database.queries`.
  - Replace the GET-only placeholder at `/expenses/<int:id>/delete` with a
    POST-only handler:
    - Guard: redirect to `/login` if not authenticated.
    - Call `get_expense_by_id(id, session["user_id"])`; if `None`, abort 404.
    - Call `delete_expense(id, session["user_id"])`.
    - Redirect to `url_for("profile")`.
  - Change the route decorator: `@app.route("/expenses/<int:id>/delete", methods=["POST"])`

- `templates/profile.html`
  - Add a delete form with a "Delete" button inside the existing "Actions" `<td>`.

- `static/css/style.css`
  - Add a `.btn-delete` style using CSS variables for danger colour
    (e.g., a red-toned variable). Never hardcode hex values.

## Files to create
No new files.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Foreign keys PRAGMA must be enabled on every connection (already done in `get_db()`)
- `delete_expense` must scope its `DELETE` to `id = ? AND user_id = ?` as an
  ownership guard — prevents one user deleting another user's expense
- The route must only accept `POST` — a bare `GET` to the URL must return 405
- Unauthenticated access must redirect to `/login` (302)
- If the expense does not exist or belongs to another user, return 404
- After successful deletion, redirect to `url_for("profile")` — do not render a template
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline styles (the `display:inline` on the `<form>` tag is the one allowed exception)
- Currency must always display as ₹ — never £ or $

## Tests to write
File: `tests/test_delete_expense.py`

### Unit tests
| Function | Input | Expected output |
|---|---|---|
| `delete_expense` | valid `expense_id`, correct `user_id` | row removed from DB |
| `delete_expense` | valid `expense_id`, wrong `user_id` | row remains in DB (0 rows deleted, no error raised) |
| `delete_expense` | non-existent `expense_id` | no error raised, DB unchanged |

### Route tests
`POST /expenses/<id>/delete` — unauthenticated:
- Redirects to `/login` (302)

`POST /expenses/<id>/delete` — authenticated, own expense:
- Redirects to `/profile` (302)
- Row no longer exists in the database

`POST /expenses/<id>/delete` — authenticated, other user's expense:
- Returns 404
- Row still exists in the database

`POST /expenses/<id>/delete` — authenticated, non-existent id:
- Returns 404

`GET /expenses/<id>/delete` — any user:
- Returns 405 (Method Not Allowed)

## Definition of done
- [ ] Visiting `POST /expenses/<id>/delete` while logged out redirects to `/login`
- [ ] `POST`ing to `/expenses/<id>/delete` for a non-existent or other user's expense returns 404
- [ ] `GET`ing `/expenses/<id>/delete` returns 405
- [ ] Clicking "Delete" on a transaction row and confirming removes that expense from the database
- [ ] After deletion, the user is redirected to `/profile` and the deleted expense no longer appears in the transaction list
- [ ] Cancelling the browser `confirm()` dialog does not submit the form and leaves the expense intact
- [ ] Each transaction row in the profile table now shows both "Edit" and "Delete" actions
