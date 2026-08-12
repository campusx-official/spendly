---
description: Create a spec file and feature branch for the next Spendly step
argument-hint: "Step number and feature name e.g. 2 registration"
allowed-tools: Read, Write, Glob, Grep, Agent, Bash(git:*)
---

You are a senior developer spinning up a new feature for the
Spendly expense tracker. Always follow the rules in CLAUDE.md.

User input: $ARGUMENTS

## Step 1 — Check working directory is clean
Run `git status` and check for uncommitted, unstaged, or
untracked files. If any exist, stop immediately and tell
the user to commit or stash changes before proceeding.
DO NOT CONTINUE until the working directory is clean.

## Step 2 — Parse the arguments
From $ARGUMENTS extract:

1. `step_number` — zero-padded to 2 digits: 2 → 02, 11 → 11

2. `feature_title` — human readable title in Title Case
   - Example: "Registration" or "Login and Logout"

3. `feature_slug` — git and file safe slug
   - Lowercase, kebab-case
   - Only a-z, 0-9 and -
   - Maximum 40 characters
   - Example: registration, login-logout

4. `branch_name` — format: `feature/<feature_slug>`
   - Example: `feature/registration`

If you cannot infer these from $ARGUMENTS, ask the user
to clarify before proceeding.

## Step 3 — Check branch name is not taken
Run `git branch` to list existing branches.
If `branch_name` is already taken, append a number:
`feature/registration-01`, `feature/registration-02` etc.

## Step 4 — Switch to main and pull latest
Run:
```
git checkout main
git pull origin main
```

## Step 5 — Create and switch to the feature branch
Run:
```
git checkout -b <branch_name>
```

## Step 6 — Research the codebase (delegate this)

`CLAUDE.md`'s Subagent Policy requires codebase research to be delegated before a
plan or spec is presented. Do not read these files yourself — launch the builtin
**`Explore`** subagent with breadth "medium" and ask it to report:

- `app.py` — every existing route, its methods, and its auth guard
- `database/db.py` — connection, schema, and `users` helpers
- `database/queries.py` — the expense and profile query helpers
- `templates/` and `static/css/` — which files already exist
- `.claude/specs/*.md` — so the new spec does not duplicate an existing one
- `tests/` — which features already have coverage

Read `CLAUDE.md` yourself for conventions and constraints; it is short and you need
it verbatim.

Then check whether the requested feature already exists. All nine original roadmap
steps are implemented, so a new spec is almost certainly step 10 or later. If the
Explore report shows the feature is already built, warn the user and stop rather
than writing a spec for finished work.

## Step 7 — Write the spec
Generate a spec document with this exact structure:

---
# Spec: <feature_title>

## Overview
One paragraph describing what this feature does and why
it exists at this stage of the Spendly roadmap.

## Depends on
Which previous steps this feature requires to be complete.

## Routes
Every new route needed:
- `METHOD /path` — description — access level (public/logged-in)

If no new routes: state "No new routes".

## Database changes
Any new tables, columns, or constraints needed.
Always verify against `database/db.py` before writing this.
If none: state "No database changes".

## Templates
- **Create:** list new templates with their path
- **Modify:** list existing templates and what changes

## Files to change
Every file that will be modified.

## Files to create
Every new file that will be created.

## New dependencies
Any new pip packages. If none: state "No new dependencies".

## Rules for implementation
Specific constraints Claude must follow. Always include:
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- DB logic goes in `database/queries.py` for anything touching `expenses`, or
  `database/db.py` for connection, schema, and `users` work — never inline in a route
- Per-resource routes must enforce ownership the way `/expenses/<id>/edit` does:
  `get_expense_by_id(id, session["user_id"])` returning `None` then `abort(404)`

## Definition of done
A specific testable checklist. Each item must be
something that can be verified by running the app.
---

## Step 8 — Save the spec
Save to: `.claude/specs/<step_number>-<feature_slug>.md`

## Step 9 — Report to the user
Print a short summary in this exact format:
```
Branch:    <branch_name>
Spec file: .claude/specs/<step_number>-<feature_slug>.md
Title:     <feature_title>
```

Then tell the user:
"Review the spec at `.claude/specs/<step_number>-<feature_slug>.md`
then enter Plan Mode with Shift+Tab twice to begin implementation.

After implementing:
  /test-feature <step_number>-<feature_slug>         write + run tests
  /code-review-feature <step_number>-<feature_slug>  security + quality review
  /ship-feature                                      commit, PR, merge, clean up"

Do not print the full spec in chat unless explicitly asked.