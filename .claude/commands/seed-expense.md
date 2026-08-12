---
description: Seed realistic dummy expenses for a specific user
argument-hint: "<user_id> <count> <months>"
allowed-tools: Read, Bash(python3:*)
---

Read `database/db.py` for the expenses table schema, the `get_db()` connection
pattern, and how `DB_PATH` is resolved. Also read `database/queries.py` — it already
has an `insert_expense(user_id, amount, category, expense_date, description)` helper.
**Reuse it** rather than writing raw INSERT SQL; `CLAUDE.md` puts all DB logic in
`database/`, and that applies to seed scripts too.

Valid categories are exactly: `Food`, `Transport`, `Bills`, `Health`,
`Entertainment`, `Shopping`, `Other` — the same list `app.py` validates against, so
seeded rows must use it or they will not match the category breakdown on `/profile`.

User input: $ARGUMENTS

## Step 1 — Parse arguments

Extract from $ARGUMENTS:
- user_id — integer
- count — integer, number of expenses to create
- months — integer, how many past months to spread them across

If any argument is missing or not a valid integer, stop and say:
"Usage: /seed-expenses <user_id> <count> <months>
Example: /seed-expenses 1 50 6"

## Step 2 — Verify user exists

Before generating anything, confirm the user_id exists 
in the users table. If not, stop and say:
"No user found with id <user_id>."

## Step 3 — Generate and insert expenses

Write and run a Python script that:

1. Spreads expenses randomly across the past <months> months
2. Uses these categories with realistic Indian descriptions 
   and amounts (₹):
   - Food: 50–800
   - Transport: 20–500
   - Bills: 200–3000
   - Health: 100–2000
   - Entertainment: 100–1500
   - Shopping: 200–5000
   - Other: 50–1000
3. Distributes categories roughly proportionally 
   (Food most common, Health and Entertainment least)
4. Uses the db connection pattern from db.py — do not 
   hardcode the database filename
5. Uses parameterised queries only — no string formatting in SQL
6. Inserts all expenses in a single transaction — 
   roll back everything if any insert fails

## Step 4 — Confirm

Print:
- How many expenses were inserted
- The date range they span
- A sample of 5 inserted records