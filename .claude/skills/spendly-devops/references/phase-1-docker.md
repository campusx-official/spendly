
# Spendly on Docker — phase 1

Goal: one image, one container, data surviving restarts, running under a real WSGI
server on port 5001.

## Prerequisites

Phase 0 from `SKILL.md` must be done: `SPENDLY_DB_PATH`,
`SPENDLY_SECRET_KEY`, gated `seed_db()`, and `/healthz` + `/readyz` routes. Without
0.1 the DB lands in the image layer and every restart wipes it. Without 0.4 the
`HEALTHCHECK` has nothing to hit.

`requirements-prod.txt` must exist (gunicorn) — and its addition must have been
raised with the user, per `CLAUDE.md`'s no-new-packages rule.

## Why gunicorn and not `python app.py`

`app.py` ends with `app.run(debug=True, port=5001)`. Two independent reasons that
cannot ship:

- `debug=True` serves the Werkzeug interactive debugger, which executes arbitrary
  Python from the browser. Reachable = fully compromised host.
- The dev server is single-threaded and explicitly not for production.

The `CMD` bypasses `__main__` entirely and imports `app:app` as a WSGI callable, so
`app.run()` never executes. The `if __name__ == "__main__"` block stays exactly as
it is for local `python app.py` use.

## Worker model — 1 process, N threads

```
--workers 1 --threads 4
```

This is deliberate, and it follows from how `database/db.py` is written.
`get_db()` opens a fresh connection per call and every helper closes it, so the
code is already **thread-safe** — no connection is shared across threads, so
SQLite's `check_same_thread` never comes up. It is not **multi-process** safe for
writes: two gunicorn worker processes writing the same file produce
`sqlite3.OperationalError: database is locked`.

One process with threads gives concurrency for a page-render workload without
cross-process write contention. Only raise `--workers` after moving off SQLite.

## Make SQLite tolerate concurrency

Add to `get_db()` in `database/db.py`, next to the existing `PRAGMA foreign_keys`:

```python
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn
```

- **WAL** lets readers proceed while a write is in flight. It is a persistent
  property of the database file, so setting it per connection is a cheap no-op
  after the first.
- **`busy_timeout = 10000`** waits up to 10s for a lock instead of failing
  instantly. Equivalent to `sqlite3.connect(..., timeout=10)` — set one, not both.

WAL creates `spendly.db-wal` and `spendly.db-shm` beside the database, so the
**directory** must be writable, not just the file. That is why `SPENDLY_DB_PATH`
points at `/data/spendly.db` and the whole `/data` directory is the volume — never
bind-mount the single file.

WAL requires real file locking. Safe on a Docker named volume, EBS, or an Azure
Managed Disk. **Never on NFS or SMB** (EFS, Azure Files) — that corrupts the DB.

## Dockerfile

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system --gid 1001 spendly \
 && useradd  --system --uid 1001 --gid spendly spendly

# Dependencies first — this layer caches until requirements change
COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

# Application code, explicitly listed. No blanket `COPY . .`
COPY app.py ./
COPY database/ ./database/
COPY templates/ ./templates/
COPY static/ ./static/

# The DB lives on a volume, never in an image layer
ENV SPENDLY_DB_PATH=/data/spendly.db
RUN mkdir -p /data && chown spendly:spendly /data
VOLUME ["/data"]

USER spendly
EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/healthz', timeout=2)"]

CMD ["gunicorn", "--bind", "0.0.0.0:5001", \
     "--workers", "1", "--threads", "4", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "app:app"]
```

Notes on specific choices:

- **`python:3.12-slim`** — `CLAUDE.md` assumes Python 3.10+. Slim over Alpine:
  Alpine's musl means no manylinux wheels, so pip compiles from source and the
  build gets slower and larger, not smaller.
- **Explicit `COPY` lines, no `COPY . .`** — belt and braces with
  `.dockerignore`. The repo root holds three committed `.db` files plus `file.txt`
  and `test.md` scratch notes; none of them belong in an image.
- **Non-root `USER`** — matters here because phase 3 sets `runAsNonRoot: true`.
  Build the habit in phase 1 so the manifest does not need a workaround.
- **`urllib` healthcheck** — `python:*-slim` ships no `curl` or `wget`. A
  non-2xx response or a connection error raises, so the exit code is nonzero and
  the container goes unhealthy. No extra packages needed.
- **`--access-logfile -`** — logs to stdout so `docker logs` and any downstream
  collector work. Never log to a file in a container.
- Kubernetes ignores `HEALTHCHECK` and uses its own probes; keep it anyway for
  phases 1-2.
- Single stage is correct here. There is no build step — no compiled assets, no
  npm, no wheels to stage — so a multi-stage build would add ceremony and save
  nothing.

## .dockerignore

Not optional. Without it, `docker build` sends the whole context including `.git`,
`venv/`, and real user databases.

```
.git
.gitignore
.github
.claude
venv/
__pycache__/
*.pyc
*.pyo
tests/
pytest.ini

# Committed databases — must never reach an image
*.db
*.db-wal
*.db-shm

.env
.DS_Store
file.txt
test.md
README.md
```

`tests/` is excluded because the runtime image does not need pytest fixtures. CI
runs tests against the checkout, not inside this image — see `references/cicd.md`.

## compose.yaml

```yaml
services:
  web:
    build: .
    image: spendly:local
    ports:
      - "5001:5001"
    environment:
      SPENDLY_SECRET_KEY: ${SPENDLY_SECRET_KEY:?set SPENDLY_SECRET_KEY in .env}
      SPENDLY_DB_PATH: /data/spendly.db
      SPENDLY_SEED: "0"
      SPENDLY_ENV: production
    volumes:
      - spendly-data:/data
    restart: unless-stopped

volumes:
  spendly-data:
```

- **`${VAR:?message}`** fails the run with that message if the variable is unset,
  instead of silently starting with a default signing key.
- **Named volume, not a bind mount** — a named volume is owned by Docker and
  avoids host UID/GID mismatches against the container's `uid 1001`. If you do
  bind-mount a host directory, `chown 1001:1001` it first or writes fail with
  `EACCES`.
- **`SPENDLY_SEED: "0"`** — flip to `"1"` only for a throwaway demo container
  where you want `demo@spendly.com` / `demo123`.
- **Host port** is `5001:5001` to keep the mental model simple. In phase 2 nginx
  fronts it and the mapping becomes `127.0.0.1:5001:5001`.

Keep `.env` beside `compose.yaml`, untracked (`.gitignore` already lists `.env`):

```
SPENDLY_SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
```

## Commands

```bash
# Build
docker build -t spendly:local .

# Run via Compose (reads .env)
docker compose up -d --build
docker compose logs -f web
docker compose ps                       # STATUS shows (healthy) once probes pass

# Verify persistence: the demo data must survive a full recreate
docker compose down && docker compose up -d
docker compose exec web python -c \
  "import os,sqlite3;print(sqlite3.connect(os.environ['SPENDLY_DB_PATH']).execute('select count(*) from expenses').fetchone())"

# Shell in (non-root, no shell utilities beyond coreutils)
docker compose exec web sh

# Back up the volume correctly — never `cp` a live SQLite file
docker compose exec web python -c \
  "import os,sqlite3;sqlite3.connect(os.environ['SPENDLY_DB_PATH']).execute(\"VACUUM INTO '/data/backup.db'\")"
docker compose cp web:/data/backup.db ./spendly-backup-$(date +%F).db

# Tear down including data (destructive)
docker compose down -v
```

`VACUUM INTO` (SQLite 3.27+, Debian bookworm ships 3.40) takes a consistent
snapshot of a live database. Copying `spendly.db` while WAL is active gives you a
file missing every committed-but-uncheckpointed transaction.

## Verification checklist

Do not call phase 1 done until all of these pass:

- [ ] `docker compose up -d` → `docker compose ps` reports `healthy`
- [ ] `curl -f localhost:5001/healthz` → `{"status":"ok"}`
- [ ] `curl -f localhost:5001/readyz` → `{"status":"ready"}`
- [ ] `GET /` renders the landing page with CSS applied (static files served)
- [ ] Register a user, add an expense, `docker compose down && up`, data still there
- [ ] `docker compose exec web whoami` → `spendly`, not `root`
- [ ] `docker history spendly:local` shows no `.db` file and no `.git`
- [ ] `docker image ls spendly:local` — expect roughly 150-200 MB
- [ ] Container logs show gunicorn startup, not `WARNING: This is a development server`
- [ ] `python -m pytest` still passes on the host — phase 0 changed `db.py` and `app.py`

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Data gone after `down`/`up` | `SPENDLY_DB_PATH` unset, DB written to `/app` | phase 0.1; confirm the volume is mounted at `/data` |
| `sqlite3.OperationalError: unable to open database file` | `/data` not writable by uid 1001 | named volume, or `chown 1001:1001` the bind-mount source |
| `attempt to write a readonly database` | WAL cannot create `-wal`/`-shm` | mount the **directory** `/data`, not the single file |
| `database is locked` | `--workers` > 1 | back to `--workers 1 --threads 4`; add WAL + `busy_timeout` |
| Container exits 0 immediately | `CMD` overridden, or gunicorn missing | check `requirements-prod.txt` is the one installed |
| `ModuleNotFoundError: No module named 'database'` | `WORKDIR` wrong or `database/` not copied | `WORKDIR /app` + `COPY database/ ./database/` |
| Health check never passes | `/healthz` route missing | phase 0.4 |
| Every deploy logs users out | `SPENDLY_SECRET_KEY` regenerated per start | pin it in `.env` / platform secret store |
| `exec format error` on a VM | image built for the wrong CPU arch | see `references/phase-2-cloud-vm.md`; build with `--platform linux/amd64` |

## Out of scope for phase 1

No nginx, no TLS, no systemd, no registry push. Compose on a laptop or a single
host, port published directly. Phase 2 adds the reverse proxy, certificates, and
boot-time supervision.
