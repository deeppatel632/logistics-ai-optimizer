# Architecture Overview

## Table of Contents

- [System Context](#system-context)
- [Component Architecture](#component-architecture)
- [Data Flow Diagrams](#data-flow-diagrams)
- [Database Design](#database-design)
- [ML Inference Pipeline](#ml-inference-pipeline)
- [Security Architecture](#security-architecture)
- [Fault Tolerance](#fault-tolerance)

---

## System Context

The Logistics AI Optimizer sits at the centre of a logistics SaaS platform. External clients submit vehicle telemetry and trigger optimization requests; the platform processes them asynchronously and exposes results through a REST API.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          External Clients                               │
│  ┌───────────────┐  ┌─────────────────────┐  ┌─────────────────────┐  │
│  │  Mobile apps  │  │  IoT GPS trackers   │  │   Partner REST APIs  │  │
│  └───────┬───────┘  └──────────┬──────────┘  └──────────┬──────────┘  │
└──────────┼───────────────────┬─┘─────────────────────────┼─────────────┘
           │                   │                            │
           ▼                   ▼                            ▼
    ┌──────────────────────────────────────────────────────────────┐
    │              NGINX Ingress (TLS, rate-limit, CORS)           │
    └──────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
    ┌──────────────────────────────────────────────────────────────┐
    │                   FastAPI Application                        │
    │  ┌─────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
    │  │Tenant Midd. │  │   Rate Limiter   │  │  JWT Auth       │  │
    │  └─────────────┘  └─────────────────┘  └─────────────────┘  │
    │  ┌──────────────────────────────────────────────────────────┐ │
    │  │  Route Handlers: health / auth / warehouses / shipments  │ │
    │  │               workers / streaming / audit                │ │
    │  └──────────────────────────────────────────────────────────┘ │
    └──────┬───────────────┬────────────────────┬───────────────────┘
           │               │                    │
     ┌─────▼──────┐  ┌─────▼──────┐     ┌──────▼─────────┐
     │  Azure SQL │  │   Redis    │     │  Kafka Broker  │
     │  Edge DB   │  │  Cache /   │     │  (KRaft mode)  │
     │ (primary + │  │  Session / │     │  9092          │
     │  replica)  │  │  Broker    │     └──────┬─────────┘
     └────────────┘  └────────────┘            │
                                       ┌───────▼──────────────┐
                                       │   Celery Workers     │
                                       │  (route optimizer,   │
                                       │   AI predictor)      │
                                       └───────┬──────────────┘
                                               │
                              ┌────────────────┼──────────────────┐
                              │                │                   │
                      ┌───────▼──────┐  ┌──────▼──────┐  ┌───────▼─────┐
                      │ Feature      │  │   Triton    │  │   MinIO     │
                      │ Store        │  │  Inference  │  │  Data Lake  │
                      │ (SQL+Redis)  │  │  Server     │  │  (S3 API)   │
                      └──────────────┘  └─────────────┘  └─────────────┘
```

---

## Component Architecture

### API Layer (FastAPI)

- **Multi-tenant middleware** (`backend/core/tenant_middleware.py`): Extracts `tenant_id` from the JWT and stores it in a `contextvars.ContextVar`. Every downstream SQL query automatically scopes results to the tenant.
- **Rate limiter** (`backend/core/limiter.py`): `slowapi` middleware; bucket per (tenant, IP). Configurable per endpoint.
- **Dependency injection** (`backend/core/dependencies.py`): `get_db()` yields a SQLAlchemy session; `get_current_user()` decodes and validates the JWT.
- **Metrics** (`backend/core/metrics.py`): Prometheus `Counter` and `Histogram` instrumentation via `prometheus-fastapi-instrumentator`.

### Event Streaming (Kafka)

Topics:

| Topic | Producer | Consumer(s) | Partitions |
|---|---|---|---|
| `vehicle-location` | Streaming API | Celery workers | 12 |
| `delivery-status` | Streaming API | Audit service | 6 |
| `inventory-update` | Streaming API | Inventory service | 6 |
| `route-optimization` | Streaming API / Celery | Celery workers | 12 |
| `ai-prediction` | Streaming API / Celery | Celery workers | 6 |

Key configuration (`kafka_producer.py`):
- `acks="all"` — waits for leader + all ISR replicas
- `compression_type="gzip"` — ~70 % message size reduction
- `retries=5`, `max_in_flight_requests_per_connection=1` — preserves ordering on retry
- `linger_ms=5` — micro-batching for throughput

### Background Workers (Celery)

- **Queue routing**: `optimize_routes` → `route-optimization` queue; `run_ai_prediction` → `ai-prediction` queue; default tasks → `default` queue.
- **Concurrency**: `--concurrency=4` per pod; Kubernetes HPA scales pods 2→8 on CPU utilisation ≥ 80 %.
- **Task idempotency**: Celery task ID stored in `idempotency_keys` table. Duplicate submissions return cached result.
- **Monitoring**: Flower UI at `:5555/flower`; all task events forwarded to Prometheus via `celery-exporter`.

### Feature Store (`backend/ml/features/feature_store.py`)

Two-tier storage:

```
read path:
  Redis (TTL=60s) ─► hit? return value
                 ─► miss → SQL SELECT → write-through to Redis → return

write path:
  SQL MERGE (upsert) → invalidate Redis key async
```

Schema — `ml_features` table:

```sql
CREATE TABLE ml_features (
    entity_id   VARCHAR(64)   NOT NULL,
    feature_name VARCHAR(128) NOT NULL,
    value        FLOAT        NOT NULL,
    updated_at   DATETIME     NOT NULL DEFAULT GETDATE(),
    created_at   DATETIME     NOT NULL DEFAULT GETDATE(),
    PRIMARY KEY (entity_id, feature_name)
);
```

### ML Inference (Triton + KServe v2)

Request flow for `predict_eta`:

```
Client POST /workers/run-ai-prediction
        │
        ▼
Celery worker: inference_service.predict_eta_from_entity(vehicle_id, distance_km)
        │
        ├─► Feature Store: get_feature_vector(vehicle_id, ["vehicle_speed","traffic_score"])
        │           └─► Redis hit (60s TTL) or SQL fallback
        │
        ├─► InferenceService.predict_eta({"distance": d, "traffic_score": t, "vehicle_speed": s})
        │           └─► model_client.infer("eta_model", inputs=[...])
        │                       └─► HTTP POST triton:8000/v2/models/eta_model/infer
        │                               └─► FP32 tensor [distance, traffic_score, speed]
        │
        └─► Return predicted ETA (float, hours)
```

### Data Lake (MinIO)

Bucket prefix layout:

```
logistics-ai-data/
├── training/        # CSV/Parquet training datasets
├── models/          # Serialised model files (.onnx, .pt)
├── inference-logs/  # Logged inference inputs/outputs for drift detection
└── exports/         # Tenant data exports
```

---

## Data Flow Diagrams

### Vehicle Location Event

```
IoT Device → POST /streaming/vehicle-location
                │
                ▼
        Kafka: vehicle-location-topic (key=vehicle_id)
                │
                ├─► Consumer Group A: feature-updater
                │       └─► FeatureStore.store_feature(vehicle_id, "vehicle_speed", v)
                │       └─► FeatureStore.store_feature(vehicle_id, "traffic_score", v)
                │
                └─► Consumer Group B: audit-logger
                        └─► Write to audit_logs table
```

### Route Optimization Request

```
POST /workers/optimize-routes
        │
        ▼
Celery task: optimize_routes.delay(tenant_id, route_data)
        │
        ├─► Fetch all vehicle features from Feature Store (batch read)
        ├─► Run OR-Tools VRP solver
        ├─► Store result in Redis (key: "route:{tenant_id}:{job_id}")
        └─► Publish completion event to route-optimization-topic
```

---

## Database Design

### Core Tables

| Table | Purpose |
|---|---|
| `users` | User accounts; `tenant_id` FK |
| `tenants` | Tenant registry |
| `warehouses` | Warehouse locations |
| `shipments` | Shipment lifecycle |
| `audit_logs` | Immutable audit trail |
| `idempotency_keys` | Deduplication for Celery tasks |
| `ml_features` | Real-time feature store |

### Tenant Isolation Strategy

All queries include `WHERE tenant_id = :tenant_id`. The tenant ID is propagated via Python `contextvars.ContextVar` set by `TenantMiddleware` on every request. A SQLAlchemy `before_execute` event hook validates that tenant context is present before any write operation.

---

## Security Architecture

- **Authentication**: RS256 JWT tokens issued by the API. Token contains `sub` (user ID), `tenant_id`, `roles`, `exp`.
- **Authorisation**: Role check via `Depends(require_role("admin"))` decorator on sensitive routes.
- **Secrets**: Kubernetes `Secrets` for DB credentials, JWT secret, MinIO keys. Docker Compose uses `.env.prod`.
- **TLS**: cert-manager issues Let's Encrypt certificates; NGINX Ingress enforces HTTPS.
- **Network policy**: Kubernetes `NetworkPolicy` restricts pod-to-pod traffic to declared rules only.

---

## Fault Tolerance

| Failure | Mitigation |
|---|---|
| API pod crash | Kubernetes liveness probe restarts pod; PDB prevents full outage |
| DB primary failure | SQLAlchemy `REPLICA_DB_URL` for reads; writes queue in Celery until primary recovers |
| Redis unavailable | Cache misses fall through to SQL; Celery retries with exponential backoff |
| Kafka broker down | `kafka-python` producer retries (5x); consumer reconnect loop with 5 s back-off |
| Triton unavailable | `TritonUnavailableError` surfaced to Celery; task retried up to 3x |
| Worker pod OOM | Kubernetes `limits.memory`; HPA ensures minimum 2 replicas |
| MinIO unavailable | boto3 retry (3x); training jobs gracefully degrade until storage recovers |
