# CLAUDE.md

## Project overview

Spendly is a lightweight personal expense tracker built with Flask and SQLite.

---

## Architecture
```
spendly/
├── app.py              # All routes — single file, no blueprints
├── database/
│   ├── db.py           # Connection + schema + users:
│   │                   #   get_db(), init_db(), seed_db(),
│   │                   #   create_user(), get_user_by_email()
│   └── queries.py      # Expense + profile reads/writes:
│                       #   insert_expense(), get_expense_by_id(),
│                       #   update_expense(), delete_expense_by_id(),
│                       #   get_user_by_id(), get_recent_transactions(),
│                       #   get_summary_stats(), get_category_breakdown()
├── templates/          # base.html + one file per page
├── static/
│   ├── css/            # style.css global; one file per page otherwise
│   └── js/main.js      # Vanilla JS only (currently empty)
├── tests/              # pytest; see "Testing" below
├── pytest.ini          # pythonpath = .
├── requirements.txt    # dev + test deps
└── .claude/            # Claude Code setup — see "Claude Code setup" below
```

**Where things belong:**
- New routes → `app.py` only, no blueprints
- DB logic → `database/` only, never inline in routes
  - connection, schema, or `users` work → `db.py`
  - anything querying `expenses`, or shaping profile data → `queries.py`
- New pages → new `.html` file extending `base.html`
- Page-specific styles → new `.css` file, not inline `<style>` tags
- Deployment artifacts → created per phase by `/deploy-phase`; paths are listed in
  `.claude/skills/spendly-devops/SKILL.md`. Update this tree when they first appear.

---

## Code style

- Python: PEP 8, snake_case for all variables and functions
- Templates: Jinja2 with `url_for()` for every internal link — never hardcode URLs
- Route functions: one responsibility only — fetch data, render template, done
- DB queries: always use parameterized queries (`?` placeholders) — never f-strings in SQL
- Error handling: use `abort()` for HTTP errors, not bare `return "error string"`

---

## Tech constraints

- **Flask only** — no FastAPI, no Django, no other web frameworks
- **SQLite only** — no PostgreSQL, no SQLAlchemy ORM, no external DB
- **Vanilla JS only** — no React, no jQuery, no npm packages
- **No new pip packages** — work within `requirements.txt` as-is unless explicitly told otherwise
- Python 3.10+ assumed — f-strings and `match` statements are fine

**The one sanctioned exception:** deployment needs a WSGI server, because
`app.run(debug=True)` exposes the Werkzeug debugger (remote code execution) and must
never face the internet. When phase 1 of the deploy path runs, `gunicorn` goes into a
new `requirements-prod.txt` (`-r requirements.txt` plus the pin) and
`requirements.txt` stays untouched. Any other new package still needs an explicit ask.

---

## Subagent Policy
- Always use a builtin explore subagent for codebase exploration 
  before implementing any new feature
- Always use a subagent to verify test results 
  after any implementation
- When asked to plan, delegate codebase research 
  to a subagent before presenting the plan
- always use a builtin plan subagent in plan mode

### DevOps requests route automatically

Any request about deploying, containerising, hosting, provisioning,
scaling, backing up, or automating the release of Spendly is DevOps
work — whether or not the user names a phase or knows a command exists.
"Can you dockerize this", "put it on EC2", "why is my pod pending",
"set up GitHub Actions" all qualify.

For those requests:

1. **Load the `spendly-devops` skill first.** Never write a
   Dockerfile, manifest, nginx config, or workflow from general
   knowledge — the skill carries traps specific to this repo (the
   hardcoded DB path, the import-time demo seed, the single-writer
   ceiling, the committed `.db` files).
2. **Delegate to a subagent, do not do it inline:**
   - `spendly-devops-engineer` to build artifacts and phase-0 code changes
   - `spendly-devops-reviewer` to audit artifacts, read-only
   - Both, in that order, via `/deploy-phase <0|1|2|3|cicd>`
3. **Relay the subagent's `## Handover` block** to the user in your own
   words — what changed, what is verified, what is still open — then
   stop and await direction.
4. **Never commit, push, or mutate live cloud or cluster state** as part
   of a DevOps request. Print the command; let the user run it.

Phase 0 of the skill is a hard prerequisite for phases 1-3. The
`UserPromptSubmit` hook at `.claude/hooks/devops_router.py` injects this
routing reminder automatically, but this policy applies whether or not
the hook fires.

---

## Commands
```bash
# Setup
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run dev server (port 5001)
python app.py

# Run all tests
pytest

# Run a specific test file
pytest tests/test_foo.py

# Run a specific test by name
pytest -k "test_name"

# Run tests with output visible
pytest -s
```

---

## Claude Code setup

`.claude/` is wired as chains: a slash command orchestrates subagents, and the
subagents load a skill for domain knowledge. Keep these references in sync — if you
rename a command, agent, or skill, update every row below and the files themselves.

| Command | Subagents (in order) | Skill loaded | Writes files? |
|---|---|---|---|
| `/create-spec <n> <name>` | `Explore` for codebase research | — | spec + branch |
| `/test-feature <spec>` | `spendly-test-writer` → `spendly-test-runner` | — | `tests/` only |
| `/code-review-feature <spec>` | `spendly-security-reviewer` ∥ `spendly-quality-reviewer` (parallel) | — | no, read-only |
| `/deploy-phase <0-3\|cicd>` | `spendly-devops-engineer` → `spendly-devops-reviewer` | `spendly-devops` | deploy artifacts |
| `/seed-user`, `/seed-expense` | — | — | DB rows only |
| `/ship-feature` | — | — | commits, PR, merge |

**Skills** live in `.claude/skills/<name>/SKILL.md`. Directory name must match the
frontmatter `name`, or the skill will not register.

| Skill | Purpose | References |
|---|---|---|
| `spendly-devops` | deploy phases 0-3 + CI/CD | `references/phase-1-docker.md`, `phase-2-cloud-vm.md`, `phase-3-kubernetes.md`, `cicd.md` |
| `spendly-ui-designer` | frontend design language | — (manual invocation only) |

**Hooks** are Python scripts in `.claude/hooks/`, registered in
`.claude/settings.json`. They invoke `python3`; on a machine without it, change the
interpreter name — do **not** add a `|| python` fallback, which would break the
blocking guard (see the note in `settings.json`).

| Hook | Event | Effect |
|---|---|---|
| `devops_router.py` | `UserPromptSubmit` | routes DevOps-shaped prompts to the chain above |
| `format_python.py` | `PostToolUse` on Write/Edit | `black` on `.py` files; no-ops if black is not installed |
| `protect_paths.py` | `PreToolUse` on Bash | exit 2 blocks destructive commands against `spendly.db`, `.env`, `migrations/` |

**Verify the wiring after changing anything in `.claude/`:**

```bash
python .claude/verify_setup.py     # 52 checks; exits non-zero on any break
```

It confirms every referenced agent, command, skill, path, DB helper, and route
actually exists, that each skill directory matches its frontmatter `name`, that
`CLAUDE.md`'s route table matches `app.py` in both directions, and that no template
hardcodes a URL. Run it whenever you rename or add a command, agent, or skill —
a broken reference fails silently at runtime otherwise.

**Boundaries between the reviewers** — do not let them overlap:

- `spendly-security-reviewer` — auth, injection, authorization, data exposure in app code
- `spendly-quality-reviewer` — naming, file placement, Flask idiom, maintainability in app code
- `spendly-devops-reviewer` — deployment artifacts only (Dockerfile, manifests, workflows)

---

## Routes

All nine roadmap steps are implemented. There are **no stub routes left**.

| Route | Methods | Access | Step |
|---|---|---|---|
| `/` | GET | public | — |
| `/register` | GET, POST | public | 02 |
| `/login` | GET, POST | public | 03 |
| `/logout` | GET | public | 03 |
| `/profile` | GET | logged-in | 04, 05, 06 |
| `/expenses/add` | GET, POST | logged-in | 07 |
| `/expenses/<int:id>/edit` | GET, POST | logged-in (owner only) | 08 |
| `/expenses/<int:id>/delete` | POST | logged-in (owner only) | 09 |
| `/analytics` | GET | logged-in | coming-soon page |
| `/terms` | GET | public | — |
| `/privacy` | GET | public | — |

Ownership is enforced in the query layer: `get_expense_by_id(id, user_id)` returns
`None` when the row belongs to someone else, and the route then calls `abort(404)`.
Keep that pattern for any new per-resource route.

`/healthz` and `/readyz` do **not** exist yet. They are phase 0 of the deploy path
— see `.claude/skills/spendly-devops/SKILL.md`.

---

## Testing

```bash
pytest                              # full suite — currently 186 passed, 0 failed
pytest tests/test_06_date_filter_profile.py
pytest -k "test_name"
pytest -s                           # visible output
```

Feature test files are named `test_<NN>_<slug>.py` with underscores throughout —
`test_06_date_filter_profile.py`, `test_07_add_expense.py`,
`test_09_delete_expense.py`. Keep that shape; hyphens break `-k` filtering.

`tests/test_hooks.py` covers the `.claude/hooks/` scripts over their real
stdin/stdout JSON contract. It exists because `protect_paths.py` shipped with five
false positives, each of which blocked an ordinary command:

| Blocked | Why |
|---|---|
| `git add -A` | `dd\b` matched the "dd" inside **add** |
| `echo 'confirm ...'` | `rm\b` matched the "rm" inside **confirm** |
| `-> arrows` in prose | `>` read as a truncating redirect |
| `>/dev/null` | same, on a discard redirect |
| `<noreply@anthropic.com>` | the closing `>` of an angle-bracketed email |

Every verb now needs a **leading** word boundary, redirects exclude arrows,
comparisons, appends and `/dev/*`, angle-bracketed tokens are stripped first, and
`git rm --cached` is allowed because it is index-only. All five are pinned as
tests. Run them after editing any hook.

Note the guard matches substrings of the command text, so it will also block a
command that merely *mentions* a protected path alongside a destructive verb — a
test harness passing `rm spendly.db` as data, for instance. That is why the hook
cases live in a file rather than inline in a shell command.

Test files patch `database.db.DB_PATH` to a `tempfile` **before importing `app`**,
so they never touch the real `spendly.db`. Reuse that pattern — do not add a
`conftest.py` that conflicts with it, and do not rely on `app.config['DATABASE']`,
which the app does not read.

Registration posts `name`, `email`, `password`, `confirm_password`. Login posts
`email`, `password`. There is no `username` field anywhere.

---

## Warnings and things to avoid

- **Never hardcode URLs** in templates — always use `url_for()`
- **Never put DB logic in route functions** — it belongs in `database/db.py` or `database/queries.py`
- **Never install new packages** mid-feature without flagging it — keep `requirements.txt` in sync
- **Never use JS frameworks** — the frontend is intentionally vanilla
- **FK enforcement is manual** — SQLite foreign keys are off by default; `get_db()` must run `PRAGMA foreign_keys = ON` on every connection
- The app runs on **port 5001**, not the Flask default 5000 — don't change this
- **`app.secret_key` is hardcoded to `"dev-secret-key"`** and `debug=True` is hardcoded in `__main__`. Fine for local dev, unsafe anywhere else — phase 0 of the deploy skill fixes both. Do not deploy without it.
- **`seed_db()` runs at import time** and creates `demo@spendly.com` / `demo123`. Harmless locally; a working backdoor on any public host.
- **There is no CSRF protection.** `/expenses/<id>/delete` accepts POST, so a third-party page can trigger a delete in a logged-in browser. Known gap — raise it, don't silently add a dependency for it.
- **There is no migration system.** `init_db()` only does `CREATE TABLE IF NOT EXISTS` and never alters existing tables. A schema change means hand-editing a live SQLite file — back it up first with `VACUUM INTO`, never `cp`.
- **The SQLite files are untracked and gitignored** (`*.db`), because they hold real user emails and password hashes. Two consequences: your local database never appears in `git status`, and switching to a branch from before the untracking will delete it from disk. It is recoverable from history — `git checkout 1c738d6 -- spendly.db` — and `python app.py` will otherwise recreate an empty one with the demo seed. **Their prior contents remain in git history from commits before the untracking**; purging that needs a history rewrite, which has not been done.