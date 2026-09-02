# Deployment

`cdms-verify` is designed to run as a Kubernetes **Deployment** that writes its
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
├── base/            # namespace and deployment
└── overlays/
    ├── dev/
    └── ...
```

Render and apply:

```bash
# Preview the fully-rendered manifests
kubectl kustomize k8s/overlays/dev

# Apply
kubectl apply -k k8s/overlays/dev
```

!!! warning "Persistent storage"
    The database is persisted using a PersistentVolumeClaim. Ensure the
    claim is backed by durable storage and is available to the Deployment.

## Concurrency

The Deployment runs a single replica. SQLite serializes writers, so only one
verification process may write to the database at a time.

## Separation of writer and reader

| Component | Role | DB access | Workload |
|-----------|------|-----------|----------|
| `cdms-verify` CLI | Writes results | read-write | Deployment |
| External report tool | Browses results | **read-only** (`mode=ro`) | Deployment + Service |

Because SQLite runs in WAL mode, the read-only report service can query the
database concurrently while the Deployment writes.
