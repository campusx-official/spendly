---
name: spendly-devops
description: Deploys and operates Spendly (Flask + SQLite) across four phases - Docker, cloud VM (AWS EC2 / Azure VM), managed Kubernetes (EKS / AKS), and CI/CD pipelines. Use whenever the user asks to deploy, host, ship, containerise, provision, scale, monitor, back up, or automate the release of Spendly, or is debugging anything infrastructure-shaped - a container, image, volume, reverse proxy, certificate, manifest, pod, or pipeline. Owns the code changes the app needs before it can run anywhere but a dev checkout, and the SQLite constraint that caps every phase at one replica.
---

# Spendly DevOps

Spendly is a Flask + SQLite expense tracker with server-rendered Jinja2 templates
and no build step. Deployment happens in four phases, each a superset of the last.

This file holds what every phase shares: the prerequisite code changes, the
invariants, the environment contract, and the SQLite ceiling. Phase detail lives in
`references/`.

## Routing — read the reference file before producing artifacts

| User asks about | Read |
|---|---|
| Dockerfile, image size, `.dockerignore`, Compose, gunicorn, local container run | `references/phase-1-docker.md` |
| EC2, Azure VM, nginx, TLS/certbot, systemd, SSM/SSH, EBS, managed disk, VM backups | `references/phase-2-cloud-vm.md` |
| EKS, AKS, manifests, PVC, Ingress, probes, HPA, kustomize, `kubectl` | `references/phase-3-kubernetes.md` |
| GitHub Actions, pytest in CI, image build/push, OIDC, branch protection | `references/cicd.md` |
| Which phase applies, cost/complexity tradeoffs, "can I scale this" | this file only |

**Read the relevant reference in full before writing a Dockerfile, manifest,
nginx config, or workflow.** Each one carries the concrete file contents, a
verification checklist, and a symptom→cause→fix table for that phase. Answering
from general Docker or Kubernetes knowledge will miss the Spendly-specific traps —
the hardcoded DB path, the import-time seed, the single-writer ceiling.

If the request spans phases ("get this from my laptop to EKS"), lay out the phase
sequence from this file, then read the references one at a time in order. Do not
load all four at once.

| Phase | Target | Reference | Replicas |
|---|---|---|---|
| 0 | Make the app deployable at all | this file | 1 |
| 1 | Docker + Compose on one host | `references/phase-1-docker.md` | 1 |
| 2 | AWS EC2 or Azure VM | `references/phase-2-cloud-vm.md` | 1 |
| 3 | Managed Kubernetes | `references/phase-3-kubernetes.md` | **still 1** |
| — | Pipelines across phases 1-3 | `references/cicd.md` | — |

Phase 0 is not optional and not skippable. Read the next section before touching a
Dockerfile.

---

## Phase 0 — four code changes every later phase depends on

The app as written cannot run outside a dev checkout. These four changes are the
prerequisite for phases 1-3. Land them, with tests passing, before any packaging
work.

Each respects the project rules in `CLAUDE.md`: routes only in `app.py`, DB logic
only in `database/`, no hardcoded URLs, parameterised queries only.

### 0.1 — DB path must come from the environment

`database/db.py` currently pins the database inside the repo root:

```python
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "spendly.db")
```

In a container that resolves to `/app/spendly.db` — inside the image layer, so
every write is lost on restart and the DB cannot live on a volume. Change it to:

```python
DB_PATH = os.environ.get(
    "SPENDLY_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "spendly.db"),
)
```

The default preserves current local behaviour exactly, so nothing breaks for
students running `python app.py`. `tests/test_06_date_filter_profile.py` already
patches `database.db.DB_PATH` after import and keeps working unchanged — that test
file even sets a `SPENDLY_TEST_DB` env var with the comment "consumed below if
db.py honours it", so an env-var DB path is already anticipated.

### 0.2 — Secret key must come from the environment

`app.py` has `app.secret_key = "dev-secret-key"`. A published app with a known
signing key means anyone can forge a session cookie and log in as any user.

```python
app.secret_key = os.environ.get("SPENDLY_SECRET_KEY", "dev-secret-key")

if os.environ.get("SPENDLY_ENV") == "production" and app.secret_key == "dev-secret-key":
    raise RuntimeError("SPENDLY_SECRET_KEY must be set when SPENDLY_ENV=production")
```

Fail loudly rather than defaulting quietly. Generate with
`python -c "import secrets; print(secrets.token_hex(32))"`.

The key must be **stable** across restarts and replicas, or every deploy silently
logs every user out. Do not generate it at startup.

### 0.3 — Seeding must be gated

`app.py` runs this at import time:

```python
with app.app_context():
    init_db()
    seed_db()
```

`seed_db()` creates `demo@spendly.com` with password `demo123`. On a public host
that is a known-credential backdoor into a real account. Gate it:

```python
with app.app_context():
    init_db()
    if os.environ.get("SPENDLY_SEED", "1") == "1":
        seed_db()
```

Every deployed phase sets `SPENDLY_SEED=0`. Local dev keeps the default and is
unaffected.

Keep `init_db()` ungated — it is idempotent (`CREATE TABLE IF NOT EXISTS`) and is
what provisions a fresh volume on first boot.

### 0.4 — Health endpoints

No route currently exists that a load balancer, Docker `HEALTHCHECK`, or Kubernetes
probe can use. `/` renders a full template and every other route either redirects
or needs a session. Add two routes to `app.py`:

```python
@app.route("/healthz")
def healthz():
    """Liveness — process is up. Deliberately does not touch the DB."""
    return {"status": "ok"}, 200


@app.route("/readyz")
def readyz():
    """Readiness — the DB is reachable and writable."""
    if not db_is_healthy():
        abort(503)
    return {"status": "ready"}, 200
```

`db_is_healthy()` goes in `database/db.py`, not inline in the route:

```python
def db_is_healthy():
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except sqlite3.Error:
        return False
```

Split liveness from readiness deliberately. A DB-touching liveness probe turns a
locked database into a restart loop, which makes the lock worse. Liveness asks "is
the process wedged", readiness asks "should traffic come here".

Both routes are public and leak nothing — no version strings, no paths, no counts.

---

## Invariants — true in every phase

**Port 5001 never changes.** `CLAUDE.md` fixes it. The container listens on 5001,
the k8s `containerPort` is 5001. Map or proxy externally (nginx `proxy_pass`,
Service `targetPort`) — never edit the app's port to suit an environment.

**Flask, SQLite, vanilla JS.** No FastAPI, no ORM, no npm, no JS framework — the
same tech constraints apply to deployment code. Infra config is not an exemption.

**New runtime dependencies must be flagged, not slipped in.** `CLAUDE.md` says
"No new pip packages — work within `requirements.txt` as-is unless explicitly told
otherwise." Phase 1 genuinely requires a WSGI server, because `app.run(debug=True)`
must never face the internet — `debug=True` exposes the Werkzeug interactive
debugger, which is remote code execution. So gunicorn is a required addition and
must be raised with the user explicitly. Keep it out of the dev dependency set:

- `requirements.txt` — unchanged, dev + test as today
- `requirements-prod.txt` — `-r requirements.txt` plus `gunicorn==23.0.0`

Then update the `CLAUDE.md` tech-constraints section in the same change so the docs
and the repo agree.

**Logs go to stdout.** The app writes nothing to disk except the SQLite file. Never
add file logging — let Docker, journald, or the cluster collect stdout.

**Secrets come from the platform, never the repo.** `.env` files stay untracked
(`.gitignore` already covers `.env`). Env vars in Compose, SSM Parameter Store or
Key Vault on a VM, a `Secret` in Kubernetes.

---

## The SQLite ceiling — say this out loud in phase 3

SQLite is a single file with a single writer. That has hard consequences:

- **Phase 1-2 are genuinely fine.** One host, one file on a local disk, one
  container. A personal expense tracker will not outgrow this.
- **Phase 3 does not scale.** A ReadWriteOnce PVC mounts to one node, so
  `replicas: 2` leaves one pod stuck `ContainerCreating` or two processes fighting
  over one file. Horizontal autoscaling is not available. You get Kubernetes'
  operational model — rollouts, probes, secrets, declarative config — but not its
  scaling story.
- **Never put a SQLite file on NFS or SMB** (EFS, Azure Files). File locking over
  those protocols is unreliable and will corrupt the database. Block storage only:
  EBS, Azure Managed Disk.

If the user wants real horizontal scale, the datastore has to change — and that
directly contradicts `CLAUDE.md`'s "SQLite only — no PostgreSQL, no SQLAlchemy ORM,
no external DB". **That is the user's call, not yours.** Present the options and
their cost, then stop and ask:

| Option | Replicas | Code change | Violates CLAUDE.md |
|---|---|---|---|
| Keep SQLite on a PVC | 1 | none | no |
| Litestream/rqlite-style replication | 1 writer | moderate | partly (new dep) |
| Managed Postgres (RDS / Azure Database) | many | rewrite `database/` | yes |

Recommendation for a teaching repo: stay on SQLite through phase 3 and treat
`replicas: 1` as a documented, deliberate constraint. It teaches the whole
Kubernetes surface honestly, and "why can't I scale this" is a better lesson than a
datastore migration that erases the project's premise.

---

## Environment variable contract

One table, referenced by all four phase files. Do not invent new names elsewhere.

| Variable | Default | Phase | Purpose |
|---|---|---|---|
| `SPENDLY_DB_PATH` | repo-root `spendly.db` | 1+ | SQLite file location |
| `SPENDLY_SECRET_KEY` | `dev-secret-key` | 1+ | session signing; **required** in prod |
| `SPENDLY_ENV` | unset | 1+ | `production` enables strict checks + secure cookies |
| `SPENDLY_SEED` | `1` | 1+ | `0` disables the demo user |
| `SPENDLY_BEHIND_PROXY` | unset | 2+ | `1` enables `ProxyFix` behind nginx/ALB |

## Where deploy artifacts live

These are new top-level paths, none of which exist yet:

```
Dockerfile                 # phase 1
.dockerignore              # phase 1
compose.yaml               # phase 1
requirements-prod.txt      # phase 1
deploy/
├── vm/                    # phase 2 — nginx.conf, spendly.service, bootstrap.sh
└── k8s/                   # phase 3 — kustomize base/ + overlays/eks, overlays/aks
.github/workflows/         # CI/CD
```

`CLAUDE.md`'s architecture tree documents none of them. Whenever you add a phase's
artifacts, update that tree and the "Where things belong" list in the same change —
the `spendly-test-writer` and `spendly-test-runner` subagents read `CLAUDE.md` for
project facts, so stale docs actively mislead them.

## Before you deploy anything: repo state to check

Both of the issues this section originally flagged have been fixed — the SQLite
files are untracked and gitignored, and the test suite is green at 186 passed. Two
things still need verifying every time, because neither is enforced by anything:

1. **`.dockerignore` must exclude `*.db`.** The database is gitignored, but it
   *does* exist on disk in any working checkout, so `docker build` would happily
   copy a developer's real database — with every user's email and password hash —
   into an image layer. `.gitignore` does not affect the build context; only
   `.dockerignore` does. Verify the entry is present before the first build.

   Related, and worth stating once to the user: the prior contents of those files
   are still in git history from commits before the untracking. Purging that needs
   a history rewrite (`git filter-repo` or BFG) plus a force-push. It has not been
   done, and it is a separate decision — do not attempt it as part of a deploy task.

2. **Confirm the suite is green before wiring CI**, with `python -m pytest -q`.
   The baseline is 186 passed, 0 failed. A red suite turns the first pipeline run
   into noise everyone learns to ignore. `python .claude/verify_setup.py` should
   also pass all its checks — it catches references in these skill files that have
   drifted from the codebase.
