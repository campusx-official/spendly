
# Spendly CI/CD

Pipelines that fit the repo's actual workflow: feature branch → PR → squash-merge
to `main` (that is what the `/ship-feature` slash command does) → deploy from `main`.

## Two blockers to clear first

**1. Three tests currently fail.** In
`tests/test_06_date_filter_profile.py::TestQueryHelpers`, the three
`*_sql_injection_does_not_crash` tests fail: 135 passed, 3 failed. They are wrong
assertions, not a vulnerability — the queries are correctly parameterised, and
`date BETWEEN "'; DROP TABLE expenses; --" AND <today>` legitimately matches every
row because `'` (ASCII 39) sorts below `2` (50). The tests assert `result == []`
when their own names say the contract is "does not crash".

Fix them to match the name before adding CI, or the pipeline is red from the first
run and everyone learns to ignore it:

```python
def test_get_category_breakdown_sql_injection_does_not_crash(self, client):
    _, user_id = client
    with app.app_context():
        # A parameterised query binds this as a literal string, so it is a
        # harmless (if nonsensical) date bound — the point is that nothing
        # executes and the table survives.
        get_category_breakdown(user_id, date_from="'; DROP TABLE expenses; --",
                               date_to=TODAY_STR)
        conn = get_db()
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='expenses'"
        ).fetchone() is not None, "expenses table must survive an injection attempt"
        conn.close()
```

**2. Test filenames are inconsistent.** `test_07-add-expense.py` uses hyphens,
`test_06_date_filter_profile.py` uses underscores, `test_delete_expense.py` has no
step number. pytest collects all three by filename glob, so the suite runs — but
`-k` filtering and any import-based tooling get awkward. Rename to underscores and a
consistent `test_<NN>_<slug>.py` scheme while the suite is small.

## Workflow 1 — tests on every PR

`.github/workflows/test.yml`

```yaml
name: tests

on:
  pull_request:
  push:
    branches: [main]

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python -m pytest -q
```

- Runs on the **checkout, not inside the image**. The runtime image excludes
  `tests/` via `.dockerignore` on purpose — a production image should not ship test
  fixtures.
- No services, no database setup. Every test file patches
  `database.db.DB_PATH` to a `tempfile` before importing `app`, so tests are
  self-contained. `pytest.ini` already sets `pythonpath = .`.
- Python 3.12 matches the `python:3.12-slim` base image from `references/phase-1-docker.md`.
  Keep them in step so CI cannot pass on a version production never runs.

## Workflow 2 — formatting

The repo's `.claude/settings.json` has a `PostToolUse` hook
(`.claude/hooks/format_python.py`) that runs `black` on every `.py` file Claude
writes. Worth knowing: **`black` is not in `requirements.txt` and is typically not
installed**, so the hook no-ops on most machines. The `PreToolUse` guard beside it
needs only the standard library, so that one does work.

Two consequences: formatting depends on whether an individual dev happened to
`pip install black`, and CI must enforce it so the outcome does not depend on which
machine wrote the code.

Also portability: the hooks invoke `python3`. That resolves on macOS, Linux, and
any Windows box with a `python3` shim on PATH, but a fresh Windows install has only
`python`. Do not "fix" this by wrapping it as `python3 x.py || python x.py` —
`protect_paths.py` signals a block with exit code 2, `||` would read that as
failure and retry against already-consumed stdin, and the guard would silently
stop blocking. Change the interpreter name instead.

```yaml
  format:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install black==24.10.0
      - run: black --check --diff .
```

`black` is a dev tool, not a runtime dependency. Pin it in a new
`requirements-dev.txt` (`-r requirements.txt` plus `black`) so the hook and CI use
one version — different black versions disagree on formatting and produce a
pipeline that fails on code the hook just "fixed".

Adding `requirements-dev.txt` is a new-package change, so flag it to the user
per `CLAUDE.md` rather than slipping it in.

## Workflow 3 — build and push on merge to main

Keyless OIDC. No long-lived cloud credentials in GitHub secrets.

```yaml
name: build

on:
  push:
    branches: [main]

permissions:
  id-token: write      # required for OIDC
  contents: read

jobs:
  build-push:
    runs-on: ubuntu-latest
    outputs:
      image: ${{ steps.meta.outputs.image }}
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<acct>:role/spendly-gha
          aws-region: ap-south-1

      - id: ecr
        uses: aws-actions/amazon-ecr-login@v2

      - id: meta
        run: echo "image=${{ steps.ecr.outputs.registry }}/spendly:${{ github.sha }}" >> "$GITHUB_OUTPUT"

      - uses: docker/setup-buildx-action@v3

      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          platforms: linux/amd64          # must match the target VM/node arch
          tags: ${{ steps.meta.outputs.image }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

Azure equivalent for the auth and push steps:

```yaml
      - uses: azure/login@v2
        with:
          client-id: ${{ vars.AZURE_CLIENT_ID }}
          tenant-id: ${{ vars.AZURE_TENANT_ID }}
          subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
      - run: az acr login --name spendlyacr
```

Rules that matter here:

- **Tag with `github.sha`, never `latest`.** A mutable tag plus
  `imagePullPolicy: IfNotPresent` means nodes run whatever they cached, and you
  cannot tell what is deployed. The commit history in this repo includes `w` and
  `temp commit`, so commit *messages* are not a reliable version signal either —
  the SHA is.
- **`permissions:` block is required.** `id-token: write` is what makes OIDC work;
  without it the AWS/Azure login step fails with a confusing token error.
- **`platforms: linux/amd64`** explicitly. GitHub's `ubuntu-latest` is x86, so an
  unpinned build lands on a Graviton `t4g` VM as `exec format error`.
- **`cache-from/to: type=gha`** — the phase 1 Dockerfile copies
  `requirements*.txt` before the app code, so the pip layer caches across builds
  and a code-only change rebuilds in seconds.

### The OIDC trust policy

Scope it to this repository and to `main`, or any repo can assume the role:

```json
{
  "Effect": "Allow",
  "Principal": { "Federated": "arn:aws:iam::<acct>:oidc-provider/token.actions.githubusercontent.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub": "repo:campusx-official/spendly:ref:refs/heads/main"
    }
  }
}
```

A wildcard `sub` like `repo:campusx-official/spendly:*` lets a PR from a fork
assume the deploy role. Pin the ref.

## Workflow 4 — deploy

Deploy jobs go in the same `build` workflow, gated on `build-push`, and target a
GitHub **Environment** with a required reviewer so a merge does not silently ship.

### Phase 2 — VM

```yaml
  deploy-vm:
    needs: build-push
    runs-on: ubuntu-latest
    environment: production
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<acct>:role/spendly-gha
          aws-region: ap-south-1
      - name: Roll the container via SSM
        run: |
          aws ssm send-command \
            --instance-ids i-0123456789abcdef0 \
            --document-name AWS-RunShellScript \
            --parameters commands='[
              "sed -i \"s|^SPENDLY_IMAGE=.*|SPENDLY_IMAGE=${{ needs.build-push.outputs.image }}|\" /etc/spendly/spendly.env",
              "systemctl restart spendly"
            ]'
      - name: Smoke test
        run: |
          for i in $(seq 1 30); do
            curl -fsS https://spendly.example.com/readyz && exit 0
            sleep 2
          done
          exit 1
```

SSM `send-command` instead of SSH: no key material in GitHub, and it matches the
"no port 22" security group from `references/phase-2-cloud-vm.md`. The smoke test is not
optional — a deploy that reports success without checking `/readyz` is just a
restart with extra steps.

### Phase 3 — Kubernetes

```yaml
  deploy-k8s:
    needs: build-push
    runs-on: ubuntu-latest
    environment: production
    permissions: { id-token: write, contents: read }
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::<acct>:role/spendly-gha
          aws-region: ap-south-1
      - run: aws eks update-kubeconfig --name spendly-cluster
      - working-directory: deploy/k8s/overlays/eks
        run: kustomize edit set image spendly=${{ needs.build-push.outputs.image }}
      - run: kubectl diff -k deploy/k8s/overlays/eks || true
      - run: kubectl apply -k deploy/k8s/overlays/eks
      - run: kubectl -n spendly rollout status deploy/spendly --timeout=180s
```

- `kustomize edit set image` keeps the manifests authoritative instead of using
  `kubectl set image`, which drifts from git.
- `rollout status --timeout` is the gate. With `strategy: Recreate` on an RWO PVC
  a rollout takes 10-30 seconds; 180s leaves room without hanging the job forever.
- `kubectl diff` before `apply` so the log shows what changed. `|| true` because
  `diff` exits non-zero whenever differences exist.
- Do not commit the `kustomize edit` result back to the repo — it creates a commit
  loop. Set it in the runner's working copy only.

## Branch protection

The pipeline only means something if `main` cannot be bypassed. On the `main`
branch require: PR before merge, `pytest` and `format` status checks passing,
branches up to date, and no force pushes.

This aligns with `/ship-feature`, which already pushes a feature branch, opens a
PR, and squash-merges — but that command merges without waiting for checks. Once
branch protection is on, the merge step will correctly block until CI is green.
Update `.claude/commands/ship-feature.md` to poll check status before merging,
otherwise the command will start failing at step 6 and look broken.

## What not to automate

- **Database migrations.** `init_db()` uses `CREATE TABLE IF NOT EXISTS` and never
  alters existing tables. There is no migration system. A schema change today
  means hand-editing a live SQLite file — do that deliberately, with a backup
  taken first, not from a pipeline. If schema churn becomes routine, that is a
  real feature request (a `migrations/` directory and a version table), not a CI
  concern. Note the `PreToolUse` hook already treats `migrations/` as protected,
  so the setup anticipates it.
- **`seed_db()` in any deployed environment.** Every deploy sets `SPENDLY_SEED=0`.
  A pipeline that seeds creates a working `demo@spendly.com` / `demo123` login on a
  public URL.
- **Backup restores.** Restoring over a live database is a decision, not a job step.

## Verification checklist

- [ ] `python -m pytest -q` is green locally before the first pipeline run
- [ ] A PR shows both `pytest` and `format` checks
- [ ] A failing test blocks the merge button
- [ ] `build` runs only on `main`, not on PRs from forks
- [ ] No cloud credentials in repo secrets — only `vars` and an OIDC role ARN
- [ ] The pushed tag is the git SHA; `latest` does not exist in the registry
- [ ] The deployed `/readyz` returns 200 after the pipeline reports success
- [ ] Image arch matches the target: `docker manifest inspect <image> | grep architecture`
- [ ] Redeploying the same SHA is a no-op, not an error
- [ ] `git grep -iE "AKIA|secret_key\s*=\s*['\"]" -- .github/` finds nothing
