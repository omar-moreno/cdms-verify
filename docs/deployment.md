# Deployment

`cdms-verify` is designed to run as a Kubernetes **CronJob** that writes its
SQLite database to a persistent location. Reporting runs as a **separate**
read-only service against the same database.

## Container image

```dockerfile
--8<-- "Dockerfile"
```

## Kubernetes with Kustomize

Manifests live under `k8s/` with a base and per-environment overlays:

```
k8s/
├── base/            # namespace, configmap, cronjob
└── overlays/
    ├── dev/
    └── prod/
```

Render and apply:

```bash
# Preview the fully-rendered manifests
kubectl kustomize k8s/overlays/prod

# Apply
kubectl apply -k k8s/overlays/prod

# Trigger a manual run from the CronJob
kubectl create job --from=cronjob/cdms-verify cdms-verify-manual -n cdms-verify
```

!!! warning "hostPath and node affinity"
    The database is persisted to a host path. Because `hostPath` is
    node-local, the CronJob **must** be pinned to the owning node via
    `nodeSelector`. Do not remove it, or a run may see an empty database.

## Concurrency

The CronJob uses `concurrencyPolicy: Forbid`. SQLite serializes writers, so
only one verification run may execute at a time.

## Separation of writer and reader

| Component | Role | DB access | Workload |
|-----------|------|-----------|----------|
| `cdms-verify` CLI | Writes results | read-write | CronJob |
| External report tool | Browses results | **read-only** (`mode=ro`) | Deployment + Service |

Because SQLite runs in WAL mode, the read-only report service can query the
database concurrently while the CronJob writes.
