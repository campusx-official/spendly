
# Spendly on a cloud VM — phase 2

Goal: the phase 1 image running on one internet-facing VM, behind nginx on HTTPS,
restarting on boot, with the database on a separate disk and backed up off-host.

Architecture, identical in shape on both clouds:

```
internet → :443 nginx (TLS) → 127.0.0.1:5001 container → /var/lib/spendly (block disk)
```

The container port stays **5001** — `CLAUDE.md` fixes it. nginx owns 80/443; the
app is never published to the internet directly.

## Prerequisites

Phase 0 (`SKILL.md`) and phase 1 (`references/phase-1-docker.md`) complete, plus two
additions specific to running behind a proxy.

### 2.1 — Trust the proxy headers

Behind nginx, Flask sees every request as HTTP from `127.0.0.1`. That breaks
`url_for(..., _external=True)` and any scheme-dependent logic. Werkzeug is already
a dependency, so no new package:

```python
from werkzeug.middleware.proxy_fix import ProxyFix

if os.environ.get("SPENDLY_BEHIND_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
```

`x_for=1` means "trust exactly one proxy". Only enable it when a proxy really is
in front — an app that trusts `X-Forwarded-For` while directly exposed lets any
client spoof its own IP.

### 2.2 — Harden the session cookie

```python
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SPENDLY_ENV") == "production",
)
```

`SECURE` stops the cookie travelling over plain HTTP. `HTTPONLY` keeps JavaScript
away from it. Tie `SECURE` to `SPENDLY_ENV` so local HTTP dev still works.

Say this to the user once, plainly: **Spendly has no CSRF protection.** With
`/expenses/<id>/delete` accepting POST, a third-party page can trigger a delete in
a logged-in browser. `SameSite=Lax` blocks the cross-site form POST case, which
covers the current routes, but it is a mitigation and not a fix. Real CSRF tokens
are a separate feature — flag it, do not silently bolt it on here.

## Cloud comparison

| Concern | AWS EC2 | Azure VM |
|---|---|---|
| Instance | `t3.small` (x86) / `t4g.small` (arm64) | `Standard_B2s` |
| OS | Ubuntu 24.04 LTS AMI | Ubuntu 24.04 LTS |
| Registry | ECR private repo | ACR (Basic) |
| Registry auth | IAM instance profile + `AmazonEC2ContainerRegistryReadOnly` | Managed identity + `AcrPull` role |
| Firewall | Security Group | Network Security Group |
| Admin access | SSM Session Manager (no port 22) | Bastion, or SSH restricted by source IP |
| Data disk | EBS gp3, 10 GB | Managed Disk (Premium SSD), 10 GB |
| Secret store | SSM Parameter Store `SecureString` | Key Vault secret |
| Static IP | Elastic IP | Static Public IP |
| Backup target | S3 bucket, versioned + lifecycle | Blob container, cool tier |

Both are single-VM, single-AZ, with downtime during a reboot. That is the correct
tradeoff for phase 2 — do not add an ALB or availability set here. A load balancer
in front of one SQLite writer buys nothing and costs more than the VM.

## Watch the CPU architecture

The most common phase 2 failure is `exec format error`. It happens when an image
built on Apple Silicon or for Graviton runs on x86, or the reverse.

```bash
# Explicit target arch, always
docker buildx build --platform linux/amd64 -t <registry>/spendly:<tag> --push .

# For t4g / Graviton
docker buildx build --platform linux/arm64 -t <registry>/spendly:<tag> --push .
```

Pick one architecture per environment and pin it in the build command. Multi-arch
manifests (`--platform linux/amd64,linux/arm64`) work but double build time for no
benefit on a single known VM.

## Firewall rules

Inbound, both clouds:

| Port | Source | Purpose |
|---|---|---|
| 443 | `0.0.0.0/0` | HTTPS |
| 80 | `0.0.0.0/0` | ACME challenge + redirect to 443 |
| 22 | **nothing** | use SSM / Bastion |

Never open 5001. If you can reach `http://<public-ip>:5001` the proxy is being
bypassed and the app is serving without TLS. Compose must bind to loopback only:

```yaml
ports:
  - "127.0.0.1:5001:5001"
```

The `127.0.0.1` prefix is the load-bearing part. `"5001:5001"` binds `0.0.0.0`,
and Docker's iptables rules bypass a UFW-style host firewall — the port ends up
reachable even though `ufw status` says otherwise.

## Host bootstrap

`deploy/vm/bootstrap.sh` — idempotent, safe to re-run:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Docker Engine + Compose plugin from Docker's own repo
curl -fsSL https://get.docker.com | sh
apt-get update && apt-get install -y nginx sqlite3 unattended-upgrades

# Data disk. Confirm the device name with `lsblk` first —
# it is /dev/nvme1n1 on Nitro EC2, /dev/sdc on many Azure VMs.
DEV=/dev/nvme1n1
blkid "$DEV" >/dev/null 2>&1 || mkfs.ext4 -L spendly "$DEV"
mkdir -p /var/lib/spendly
grep -q 'LABEL=spendly' /etc/fstab || \
  echo 'LABEL=spendly /var/lib/spendly ext4 defaults,nofail 0 2' >> /etc/fstab
mount -a

# uid/gid must match the container's non-root user
chown 1001:1001 /var/lib/spendly
```

Mount by `LABEL=` or `UUID=`, never by device path — device names are not stable
across reboots or instance-type changes, and a wrong path in `/etc/fstab` without
`nofail` leaves the VM unbootable.

`chown 1001:1001` matches the `spendly` user baked into the image in phase 1. A
bind mount preserves host ownership, so without this the container cannot write and
you get `unable to open database file`.

## Compose on the VM

`/srv/spendly/compose.yaml` — differs from phase 1 in three ways: a registry image
instead of `build:`, loopback-only binding, and a host bind mount instead of a
named volume (so backups can read the file directly).

```yaml
services:
  web:
    image: ${SPENDLY_IMAGE:?set SPENDLY_IMAGE to a digest or sha tag}
    ports:
      - "127.0.0.1:5001:5001"
    environment:
      SPENDLY_SECRET_KEY: ${SPENDLY_SECRET_KEY:?fetch from SSM or Key Vault}
      SPENDLY_DB_PATH: /data/spendly.db
      SPENDLY_ENV: production
      SPENDLY_SEED: "0"
      SPENDLY_BEHIND_PROXY: "1"
    volumes:
      - /var/lib/spendly:/data
    restart: unless-stopped
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "3" }
```

Set `logging` limits or `json-file` grows until the root disk fills — a classic
way to lose a small VM.

Pin `SPENDLY_IMAGE` to a git SHA tag or a digest, never `:latest`. With `:latest`
you cannot tell what is running and `docker compose up` may or may not pull.

## Secrets at boot

Fetch into a root-only env file; never commit it.

```bash
# AWS
aws ssm get-parameter --name /spendly/secret-key --with-decryption \
  --query Parameter.Value --output text > /etc/spendly/spendly.env.tmp

# Azure
az keyvault secret show --vault-name spendly-kv --name secret-key \
  --query value -o tsv > /etc/spendly/spendly.env.tmp
```

Wrap it as `SPENDLY_SECRET_KEY=<value>`, then
`install -m 600 -o root -g root /etc/spendly/spendly.env.tmp /etc/spendly/spendly.env`.

The VM's instance profile / managed identity provides the credentials. Never put
long-lived access keys on the VM.

## systemd unit

`/etc/systemd/system/spendly.service` — makes Compose survive reboots.

```ini
[Unit]
Description=Spendly (docker compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/srv/spendly
EnvironmentFile=/etc/spendly/spendly.env
ExecStartPre=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

`Type=oneshot` + `RemainAfterExit=yes` is the right pairing for Compose: the
command exits immediately but the unit should still count as active. `restart:
unless-stopped` in Compose handles container crashes; systemd handles host reboots.

```bash
systemctl enable --now spendly
systemctl status spendly
```

## nginx

`/etc/nginx/sites-available/spendly`:

```nginx
server {
    listen 80;
    server_name spendly.example.com;

    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    http2 on;
    server_name spendly.example.com;

    ssl_certificate     /etc/letsencrypt/live/spendly.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/spendly.example.com/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
    }
}
```

- `X-Forwarded-Proto` is what `ProxyFix` reads to learn the request was HTTPS.
  Without it `SESSION_COOKIE_SECURE` cookies are set on a connection Flask thinks
  is plaintext and users cannot stay logged in.
- `http2 on;` is the current directive. `listen 443 ssl http2;` is deprecated in
  nginx 1.25+ and warns on reload.
- Let gunicorn serve `/static/`. An nginx `alias` is faster, but it needs the
  static files on the host filesystem, which means a second copy to keep in sync
  with the image. Not worth it at this scale — revisit only if static latency is
  measurably a problem.
- `add_header ... always` so the headers apply to error responses too.

```bash
ln -sf /etc/nginx/sites-available/spendly /etc/nginx/sites-enabled/spendly
rm -f /etc/nginx/sites-enabled/default        # else it wins on the default vhost
nginx -t && systemctl reload nginx
```

## TLS

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d spendly.example.com --agree-tos -m ops@example.com --no-eff-email
systemctl list-timers | grep certbot        # renewal timer installs automatically
```

DNS must resolve to the VM's static IP before running certbot, or the HTTP-01
challenge fails. Allocate the Elastic IP / static Public IP first — a default
public IP changes on stop/start and silently breaks both DNS and the certificate.

## Backups

`/etc/cron.daily/spendly-backup`, `chmod 755`:

```bash
#!/usr/bin/env bash
set -euo pipefail
STAMP=$(date -u +%FT%H%M%SZ)
TMP=/tmp/spendly-$STAMP.db

sqlite3 /var/lib/spendly/spendly.db "VACUUM INTO '$TMP'"

# AWS
aws s3 cp "$TMP" "s3://spendly-backups/db/spendly-$STAMP.db" --storage-class STANDARD_IA
# Azure
# az storage blob upload --account-name spendlybackups -c db \
#   -n "spendly-$STAMP.db" -f "$TMP" --auth-mode login

rm -f "$TMP"
```

**`VACUUM INTO`, not `cp`.** With WAL enabled, `cp spendly.db` copies the main file
and misses every transaction still sitting in `spendly.db-wal` — a silently
truncated backup that restores clean and is missing data. `VACUUM INTO` produces a
consistent, already-compacted snapshot of a live database.

Restore, and test it before you need it:

```bash
systemctl stop spendly
aws s3 cp s3://spendly-backups/db/spendly-<stamp>.db /var/lib/spendly/spendly.db
chown 1001:1001 /var/lib/spendly/spendly.db
rm -f /var/lib/spendly/spendly.db-wal /var/lib/spendly/spendly.db-shm
systemctl start spendly
```

Deleting the stale `-wal`/`-shm` files matters — leaving them beside a restored
database mixes two different histories.

Bucket/container must be private with versioning on. These files contain every
user's email, password hash, and full spending history.

## Deploy a new version

```bash
export SPENDLY_IMAGE=<registry>/spendly:<git-sha>
sed -i "s|^SPENDLY_IMAGE=.*|SPENDLY_IMAGE=$SPENDLY_IMAGE|" /etc/spendly/spendly.env
systemctl restart spendly
curl -fsS https://spendly.example.com/readyz
```

Expect a few seconds of 502 during restart. One container, one database, no
zero-downtime story — that is inherent to phase 2, and worth stating plainly
rather than papering over. Zero-downtime rollouts arrive in phase 3, and even
there `strategy: Recreate` means a brief gap.

## Verification checklist

- [ ] `https://spendly.example.com/` serves the landing page with a valid certificate
- [ ] `http://` redirects to `https://` with 301
- [ ] `curl http://<public-ip>:5001` times out — port not reachable
- [ ] `/readyz` returns 200
- [ ] Register, log in, add an expense; `systemctl reboot`; data and session survive
- [ ] Session cookie shows `Secure`, `HttpOnly`, `SameSite=Lax` in devtools
- [ ] `docker compose exec web whoami` → `spendly`
- [ ] `curl -sI https://.../ | grep -i strict-transport` present
- [ ] Backup cron produced an object; a restore into a scratch VM opens cleanly
- [ ] `systemctl is-enabled spendly` → `enabled`
- [ ] No SSH inbound rule; SSM/Bastion session works
- [ ] `demo@spendly.com` / `demo123` does **not** log in (`SPENDLY_SEED=0`)

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `exec format error` | image arch ≠ VM arch | rebuild with `--platform` |
| 502 from nginx | container down, or bound to the wrong interface | `docker compose ps`; confirm `127.0.0.1:5001:5001` |
| Login loop, cookie never sticks | `SECURE` cookie + missing `X-Forwarded-Proto` | add the header; set `SPENDLY_BEHIND_PROXY=1` |
| certbot HTTP-01 fails | DNS not pointing at the VM, or 80 closed | fix DNS/SG first |
| `unable to open database file` | `/var/lib/spendly` not owned by 1001 | `chown 1001:1001` |
| Root disk full | unbounded `json-file` logs | add the `logging` limits above |
| Restored backup missing recent data | `cp` used instead of `VACUUM INTO` | fix the backup script |
| App unreachable after stop/start | ephemeral public IP changed | allocate a static IP |
| Container not up after reboot | unit not enabled | `systemctl enable spendly` |

## Out of scope

No autoscaling, no multi-AZ, no managed database, no Terraform/CloudFormation in
this skill (if the user wants IaC, that is a separate ask — and note the repo has
no IaC today). Phase 3 in `references/phase-3-kubernetes.md` replaces nginx+systemd with
Ingress+Deployment; the container image and the environment contract carry over
unchanged.
