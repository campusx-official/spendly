
# Spendly on managed Kubernetes — phase 3

Goal: the same phase 1 image running as a single-replica Deployment with a
persistent volume, declarative config, real probes, and TLS at the Ingress.

## Read this before writing a single manifest

**`replicas: 1` is a hard ceiling, not a starting point.** SQLite is one file with
one writer. A ReadWriteOnce PVC attaches to one node at a time. So:

- `replicas: 2` → the second pod hangs in `ContainerCreating` (`Multi-Attach error
  for volume`), or if scheduled to the same node, two processes corrupt-race one file
- `HorizontalPodAutoscaler` → cannot be used at all
- `strategy: RollingUpdate` → the default `maxSurge: 25%` tries to start a new pod
  before terminating the old one, both wanting the same RWO volume. Deadlock on
  every deploy. **`strategy: Recreate` is mandatory.**

You get Kubernetes' operational model — declarative config, probes, secret
management, rollout history, ingress — but not its scaling story. That is a real,
worthwhile phase 3. Say it to the user up front so nobody discovers it at
`kubectl scale` time.

If they want genuine horizontal scale, the datastore must change, which
contradicts `CLAUDE.md`'s "SQLite only — no PostgreSQL, no SQLAlchemy ORM, no
external DB". **Stop and ask.** See the options table in `SKILL.md`. Do not
migrate `database/` off SQLite on your own initiative.

**Never back the PVC with NFS or SMB** — EFS, Azure Files, or any `ReadWriteMany`
class. SQLite's locking is unreliable over those protocols and WAL mode will
corrupt the database. Block storage only: EBS `gp3` (EKS) or Azure Managed Disk
(AKS), both inherently `ReadWriteOnce`.

## Prerequisites

Phase 0 (`SKILL.md`) and phase 1 (`references/phase-1-docker.md`) complete. Also carry over
`ProxyFix` and the hardened session cookie from `references/phase-2-cloud-vm.md` §2.1-2.2 — an
Ingress controller is a reverse proxy, so `SPENDLY_BEHIND_PROXY=1` applies here too.

Image must be in ECR (EKS) or ACR (AKS), tagged with a git SHA. Never `:latest` —
with `imagePullPolicy: IfNotPresent` a mutable tag means nodes silently run
whatever they cached.

## Layout

`deploy/k8s/`, kustomize base plus one overlay per cloud:

```
deploy/k8s/
├── base/
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── pvc.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   └── backup-cronjob.yaml
└── overlays/
    ├── eks/kustomization.yaml    # gp3 StorageClass, ALB annotations, ECR image
    └── aks/kustomization.yaml    # managed-csi StorageClass, AGIC/nginx, ACR image
```

Overlays patch only what differs per cloud: StorageClass name, Ingress class and
annotations, image registry, hostname. Everything else stays in `base/`.

## Manifests

### namespace.yaml

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: spendly
```

### configmap.yaml — non-secret config only

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: spendly-config
  namespace: spendly
data:
  SPENDLY_DB_PATH: /data/spendly.db
  SPENDLY_ENV: production
  SPENDLY_SEED: "0"
  SPENDLY_BEHIND_PROXY: "1"
```

`SPENDLY_SEED: "0"` matters — leaving it at the default `1` publishes
`demo@spendly.com` / `demo123` as a working login on a public URL.

### The Secret — do not commit it

`SPENDLY_SECRET_KEY` never goes in a ConfigMap or a tracked YAML file. Base64 in a
manifest is encoding, not encryption. Create it out of band:

```bash
kubectl -n spendly create secret generic spendly-secrets \
  --from-literal=secret-key="$(python -c 'import secrets;print(secrets.token_hex(32))')"
```

The key must stay **stable** — rotating it invalidates every session cookie and
logs all users out. For a managed flow use the External Secrets Operator or the
Secrets Store CSI driver against SSM Parameter Store / Key Vault; that is a
cluster-level concern, so mention it and move on rather than building it here.

### pvc.yaml

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: spendly-data
  namespace: spendly
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 5Gi
  # storageClassName is set per-cloud in the overlay
```

5Gi is generous — the seeded database is a few KB — but most block-storage classes
have a minimum and cannot shrink later. Check `allowVolumeExpansion: true` on the
StorageClass so growth is possible.

### deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spendly
  namespace: spendly
spec:
  replicas: 1                 # HARD LIMIT — SQLite has one writer, PVC is RWO
  strategy:
    type: Recreate            # RollingUpdate deadlocks on the RWO volume
  selector:
    matchLabels:
      app: spendly
  template:
    metadata:
      labels:
        app: spendly
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001       # matches the image's `spendly` user
        runAsGroup: 1001
        fsGroup: 1001         # makes the mounted PVC writable by that user
      containers:
        - name: web
          image: <registry>/spendly:<git-sha>
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 5001
          envFrom:
            - configMapRef:
                name: spendly-config
          env:
            - name: SPENDLY_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: spendly-secrets
                  key: secret-key
          livenessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 10
            periodSeconds: 20
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /readyz
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: data
              mountPath: /data
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: spendly-data
        - name: tmp
          emptyDir: {}
```

Why each of these:

- **`fsGroup: 1001`** — the CSI driver formats a fresh volume as root-owned. Without
  `fsGroup` the container's non-root user cannot write and the pod crash-loops on
  `unable to open database file`.
- **`readOnlyRootFilesystem: true`** plus an `emptyDir` at `/tmp` — gunicorn needs
  a writable temp dir, and nothing else in the image writes to disk. Set
  `PYTHONDONTWRITEBYTECODE=1` in phase 1, so no `.pyc` writes either.
- **`/healthz` for liveness, `/readyz` for readiness** — this split is the whole
  point of having two endpoints. A DB-touching liveness probe turns a locked
  database into a kill-and-restart loop, which makes the lock worse. Liveness asks
  "is the process wedged", readiness asks "should traffic come here".
- **`memory` limit** — with a `limits.memory` and no request/limit mismatch this
  pod is Burstable. Exceeding the memory limit is an OOMKill, not throttling; 256Mi
  is comfortable for one gunicorn process with 4 threads.
- **`envFrom` + one `env`** — bulk non-secret config from the ConfigMap, the single
  secret referenced individually. Never flatten the secret into `envFrom`.

Note `Recreate` means a brief outage on every rollout — the old pod must fully
terminate and detach the volume before the new one attaches. Typically 10-30
seconds. That is inherent, not a misconfiguration.

### service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: spendly
  namespace: spendly
spec:
  type: ClusterIP
  selector:
    app: spendly
  ports:
    - name: http
      port: 80
      targetPort: http     # resolves to containerPort 5001
```

`targetPort: http` references the named port, so the app stays on 5001 per
`CLAUDE.md` while the Service speaks 80 internally. `ClusterIP`, not `LoadBalancer`
— the Ingress owns external exposure.

### ingress.yaml (base — annotations come from the overlay)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: spendly
  namespace: spendly
spec:
  rules:
    - host: spendly.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: spendly
                port:
                  number: 80
```

### backup-cronjob.yaml

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: spendly-backup
  namespace: spendly
spec:
  schedule: "0 2 * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          securityContext:
            runAsNonRoot: true
            runAsUser: 1001
            fsGroup: 1001
          containers:
            - name: backup
              image: <registry>/spendly:<git-sha>   # reuse the app image, python+sqlite3 present
              command:
                - python
                - -c
                - |
                  import os, sqlite3, datetime
                  stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                  sqlite3.connect(os.environ["SPENDLY_DB_PATH"]).execute(
                      f"VACUUM INTO '/data/backups/spendly-{stamp}.db'"
                  )
              envFrom:
                - configMapRef:
                    name: spendly-config
              volumeMounts:
                - name: data
                  mountPath: /data
          volumes:
            - name: data
              persistentVolumeClaim:
                claimName: spendly-data
```

Two things to be honest about:

1. **This CronJob cannot run while the app pod holds the RWO volume** on most CSI
   drivers — the Job pod will sit in `ContainerCreating` with a multi-attach error
   unless it lands on the same node. Options: schedule it as a sidecar in the app
   pod instead, use `VolumeSnapshot` on the PVC (the cleanest cloud-native answer),
   or accept a brief `Recreate` window. Pick with the user.
2. **A backup on the same PVC is not a backup.** Volume dies, backup dies with it.
   Add an upload step to S3/Blob using IRSA (EKS) or Workload Identity (AKS), or
   use `VolumeSnapshot` with snapshots stored outside the volume.

Use `VACUUM INTO`, never `cp` — with WAL enabled a plain copy silently omits
transactions still in `spendly.db-wal`.

## Cloud-specific overlays

| Concern | EKS | AKS |
|---|---|---|
| StorageClass | `gp3` (EBS CSI driver, install as an add-on) | `managed-csi-premium` |
| Ingress controller | AWS Load Balancer Controller → ALB | AGIC → App Gateway, or `ingress-nginx` |
| `ingressClassName` | `alb` | `azure-application-gateway` or `nginx` |
| TLS | ACM cert via `alb.ingress.kubernetes.io/certificate-arn` | cert-manager, or App Gateway listener cert |
| ALB scheme | `alb.ingress.kubernetes.io/scheme: internet-facing` | — |
| ALB health check | `alb.ingress.kubernetes.io/healthcheck-path: /healthz` | probes come from the readiness probe |
| Registry auth | node role or Pod Identity with ECR read | `az aks update --attach-acr` |
| Pod → AWS/Azure API | IRSA or EKS Pod Identity | Workload Identity |

EKS overlay Ingress annotations:

```yaml
metadata:
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP":80},{"HTTPS":443}]'
    alb.ingress.kubernetes.io/ssl-redirect: "443"
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:<region>:<acct>:certificate/<id>
spec:
  ingressClassName: alb
```

The `gp3` StorageClass is not present by default on EKS — install the EBS CSI
driver add-on and create the class, or the PVC stays `Pending` forever with
`no persistent volumes available`.

## Commands

```bash
# Never `kubectl apply` blind — diff first
kubectl diff  -k deploy/k8s/overlays/eks
kubectl apply -k deploy/k8s/overlays/eks

kubectl -n spendly rollout status deploy/spendly
kubectl -n spendly get pods,pvc,svc,ingress
kubectl -n spendly logs deploy/spendly -f
kubectl -n spendly describe pod -l app=spendly     # events explain Pending/CrashLoop

# Local smoke test without going through the Ingress
kubectl -n spendly port-forward deploy/spendly 5001:5001
curl -f localhost:5001/readyz

# Roll back
kubectl -n spendly rollout undo deploy/spendly

# Update the image (record the SHA, do not mutate a tag)
kubectl -n spendly set image deploy/spendly web=<registry>/spendly:<git-sha>
```

Prefer `kubectl apply -k` from a pipeline over `set image` by hand, so the
manifests remain the source of truth. See `references/cicd.md`.

## Verification checklist

- [ ] `kubectl -n spendly get pod` → `1/1 Running`, `READY` true, 0 restarts
- [ ] `kubectl -n spendly get pvc` → `Bound`
- [ ] `https://spendly.example.com/` serves the landing page with a valid certificate
- [ ] `/readyz` returns 200 through the Ingress
- [ ] Register a user, add an expense, `kubectl delete pod -l app=spendly`, data survives
- [ ] `kubectl -n spendly exec deploy/spendly -- id` → `uid=1001`
- [ ] `kubectl -n spendly exec deploy/spendly -- touch /x` → fails (read-only rootfs)
- [ ] `SPENDLY_SECRET_KEY` appears in no tracked file: `git grep -i secret_key -- deploy/`
- [ ] `demo@spendly.com` / `demo123` does not log in
- [ ] `kubectl scale --replicas=2` → second pod fails to start; **this is expected**,
      confirm the user understands why before closing out the phase
- [ ] A rollout completes and `rollout undo` returns to the previous SHA

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Pod `Pending`, `no persistent volumes available` | StorageClass missing or wrong name | install EBS CSI add-on; fix `storageClassName` in the overlay |
| Pod `ContainerCreating`, `Multi-Attach error` | RWO volume held by another pod | `replicas: 1` + `strategy: Recreate` |
| Deploy hangs forever on rollout | `RollingUpdate` with an RWO PVC | switch to `Recreate` |
| `CrashLoopBackOff`, `unable to open database file` | volume root-owned, container non-root | add `fsGroup: 1001` |
| `CrashLoopBackOff`, `Read-only file system` | `readOnlyRootFilesystem` with no writable temp | `emptyDir` at `/tmp` |
| `CreateContainerConfigError` | Secret or ConfigMap missing | create `spendly-secrets`; check the namespace |
| Readiness never passes | `/readyz` route missing, or DB unreachable | phase 0.4; check the PVC mount |
| Liveness restarts under load | liveness probe touching the DB | liveness → `/healthz` (no DB) |
| `ImagePullBackOff` | registry auth missing | `--attach-acr` (AKS) or ECR perms on the node role |
| Login loop over HTTPS | Ingress not forwarding proto | `SPENDLY_BEHIND_PROXY=1` + `ProxyFix` |
| HPA created but never scales | SQLite single-writer ceiling | delete the HPA; scaling needs a datastore change |
| Data gone after pod delete | `emptyDir` used instead of the PVC | mount `spendly-data` at `/data` |

## Out of scope

No service mesh, no multi-region, no managed database migration (that is a user
decision — see `SKILL.md`), and no cluster provisioning. This reference assumes a
cluster already exists; creating one is a separate concern and the repo has no IaC
today.
