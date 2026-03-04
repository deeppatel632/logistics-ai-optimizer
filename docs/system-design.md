# System Design — Logistics AI Optimizer

> This document follows the format of a structured system design interview.  
> It explains the rationale behind every major architectural decision.

---

## 1. Problem Statement

Design a distributed backend system that:

1. Tracks the real-time GPS positions of up to **50 000 vehicles** across multiple logistics companies (tenants).
2. Continuously **re-optimises delivery routes** as traffic conditions change.
3. Serves **ML-based ETA predictions** with a p99 latency ≤ 100 ms under peak load.
4. Stores all telemetry, shipment events, and prediction logs durably for downstream training pipelines.
5. Operates as a **multi-tenant SaaS** — each company's data must be strictly isolated.

---

## 2. Functional Requirements

| # | Requirement |
|---|---|
| FR-1 | Accept real-time GPS events from IoT devices at ≥ 10 000 events/sec peak |
| FR-2 | Persist per-vehicle features (speed, traffic score) and serve them for inference in < 5 ms |
| FR-3 | Run route optimisation jobs asynchronously; surface result via polling endpoint |
| FR-4 | Infer ETA for a single vehicle in ≤ 50 ms end-to-end |
| FR-5 | Batch-infer ETA for entire fleet (up to 500 vehicles) in ≤ 500 ms |
| FR-6 | Issue JWT tokens; enforce per-tenant data isolation |
| FR-7 | Expose metrics for every API endpoint (throughput, latency, error rate) |
| FR-8 | Store training datasets and model artefacts in durable object storage |

---

## 3. Non-Functional Requirements

| # | Requirement | Target |
|---|---|---|
| NFR-1 | Availability | 99.9 % (≤ 8.7 h downtime/year) |
| NFR-2 | API p99 latency | ≤ 100 ms (excluding ML inference) |
| NFR-3 | ML inference p99 | ≤ 100 ms (Triton + FP32) |
| NFR-4 | Kafka event lag | ≤ 2 s under sustained load |
| NFR-5 | Horizontal scalability | API pods: 2–10; Worker pods: 2–8 (HPA) |
| NFR-6 | Data isolation | Zero cross-tenant data leakage |
| NFR-7 | Audit trail | 100 % of write operations logged |
| NFR-8 | Observability | Every service exports Prometheus metrics |

---

## 4. Capacity Estimates

### Traffic

- **Peak GPS events**: 50 000 vehicles × 1 event/sec = **50 000 events/sec**
- **API requests**: 50 000 events routed through `/streaming/vehicle-location` = 50 krps peak
- **Route optimization jobs**: ~500 jobs/min during peak business hours
- **ETA inference**: ~200 req/s during dispatch windows

### Storage

- GPS event size: ~200 B compressed (gzip)  → 50 000 × 200 B = **10 MB/sec raw, ~3 MB/sec compressed**
- Daily GPS volume: ~250 GB uncompressed, ~75 GB compressed
- Feature store: 50 000 vehicles × ~10 features × 16 B ≈ **8 MB** (fits in Redis entirely)
- Kafka retention: 7 days × 75 GB ≈ **525 GB** per topic partition group

### Compute

- API pods: 2 at idle; 10 at peak (HPA target CPU 70 %)
- Celery workers: 2 at idle; 8 at peak (HPA target CPU 80 %)
- Redis: single shard sufficient for feature store; sentinel or cluster for HA

---

## 5. High-Level Architecture

```
Internet  →  NGINX Ingress (TLS, rate-limit)
               │
               ▼
          FastAPI (2-10 pods, stateless)
               │
        ┌──────┴───────┐
        │              │
      SQL DB        Kafka Bus
      (RDBMS)   (10 000+ events/s)
                       │
                 Celery Workers (2-8 pods)
                       │
              ┌────────┴────────┐
              │                 │
        Feature Store      Triton Server
        (SQL + Redis)      (ML inference)
              │
           MinIO
          (Data Lake)
```

---

## 6. API Gateway Design

The API layer is **stateless** — all state lives in SQL, Redis, or Kafka. This enables horizontal scaling without sticky sessions.

### Request lifecycle

```
1. NGINX Ingress: TLS termination, rate-limit (req/s per IP), CORS
2. FastAPI TenantMiddleware: extract tenant_id from JWT, set ContextVar
3. JWT validation: RS256 signature check, expiry, roles
4. Rate limiter (slowapi): per (tenant, IP) bucket
5. Route handler: business logic, call services
6. Service layer: SQL reads (replica), SQL writes (primary), Redis cache
7. Response: JSON + Prometheus metrics emitted
```

### Authentication

- `POST /auth/register` → bcrypt-hash password, write `users` table, return JWT  
- `POST /auth/login` → verify bcrypt, issue JWT (sub=user_id, tenant_id, roles, exp)  
- Every protected endpoint declares `Depends(get_current_user)` — decoded user injected

---

## 7. Event Streaming Design

### Why Kafka over direct DB writes?

| Approach | Problem |
|---|---|
| Direct DB write per GPS event | DB becomes bottleneck at 50 krps; causes write amplification |
| Redis pub/sub | No persistence; events lost on restart |
| Kafka | Persistent, partitioned, replayable; decouples producers from consumers |

### Topic partitioning strategy

`vehicle-location-topic` is partitioned by `vehicle_id`. This guarantees:

1. **Ordering** — events for the same vehicle are processed in order.
2. **Parallelism** — 12 partitions × 4 threads/consumer = 48 concurrent event processors.
3. **Locality** — feature updates for a vehicle are never racing across partitions.

### Consumer group isolation

Two independent consumer groups subscribe to `vehicle-location-topic`:
- `feature-updater` — writes speed/traffic features to the Feature Store
- `audit-logger` — writes to the audit log table

This provides fan-out without coupling the two concerns.

---

## 8. Distributed Background Jobs

### Why Celery over Kafka consumers for heavy work?

| Aspect | Kafka consumer | Celery |
|---|---|---|
| Task retry | Manual | Automatic, exponential backoff |
| Progress tracking | None | `PROGRESS` state, `task_id` polling |
| Prioritisation | Partition ordering only | Multiple queues with priorities |
| UI | None | Flower dashboard |

### Queue routing

```python
task_routes = {
    "optimize_routes":    {"queue": "route-optimization"},
    "run_ai_prediction":  {"queue": "ai-prediction"},
    "*":                  {"queue": "default"},
}
```

Heavy VRP solver tasks go to a dedicated queue, preventing them from blocking faster prediction tasks.

### Idempotency

Every Celery task begins by checking `idempotency_keys` table:

```sql
INSERT INTO idempotency_keys (key, result) VALUES (:key, NULL)
-- ON CONFLICT: return cached result
```

The idempotency key = `SHA256(task_name + sorted(args))`. Retriggers within a 24-hour window are deduplicated.

---

## 9. ML Inference Pipeline

### Design goals

- **Training-serving skew elimination**: The same SQL schema (`ml_features` table) is used by both offline training scripts and the online Feature Store. There is no separate transformation layer.
- **Low latency**: Features pre-computed at ingest time (GPS events → Feature Store). At inference time, a single SQL batch read fetches the entire feature vector — no expensive JOINs.
- **Model versioning**: Models stored in MinIO under `models/{model_name}/v{version}/model.onnx`. Triton loads via model repository mount.

### Batch vs single inference

```python
# Single: 1 Triton HTTP round-trip
predict_eta(features: dict) → float

# Batch: 1 Triton HTTP round-trip for N vehicles
batch_predict_eta([features, features, ...]) → [float, ...]
```

Batch inference is more efficient because it amortises the HTTP overhead and allows Triton to process the tensor batch on the GPU in a single kernel.

---

## 10. Database Design

### Primary vs Replica split

```
Writes → PRIMARY (sql_edge:1433, Azure SQL Edge)
Reads  → REPLICA  (configurable REPLICA_DB_URL)
```

SQLAlchemy `sessionmaker` for primary uses `DB_URL`. Read-heavy queries (warehouse list, audit log) use the replica session. This doubles effective read throughput without any application-level sharding.

### Connection pooling

```
pool_size=10, max_overflow=20, pool_timeout=30, pool_recycle=1800
```

With 10 API pods × 10 connections each = 100 max concurrent connections to the primary. The `pool_recycle=1800` prevents holding stale connections past the Azure SQL Edge idle timeout.

See [SCALING_STRATEGY.md](SCALING_STRATEGY.md) for the full connection pooling analysis.

### Soft delete

All domain tables (`warehouses`, `shipments`, `users`) have:
```
deleted_at  DATETIME NULL
deleted_by  VARCHAR(64) NULL
```

Queries filter `WHERE deleted_at IS NULL`. Deleted records remain for audit purposes and can be restored.

---

## 11. Caching Strategy

| Cache layer | What is cached | TTL | Eviction |
|---|---|---|---|
| Redis (Feature Store) | ML features per vehicle | 60 s | TTL expiry + explicit invalidation on write |
| Redis (session) | JWT → decoded user | JWT expiry | TTL expiry |
| Redis (task result) | Celery task outputs | 24 h | TTL expiry |
| Redis (route cache) | Optimised routes | 5 min | TTL expiry |

The 60-second Feature Store TTL was chosen based on GPS update frequency (1 Hz) and acceptable staleness for inference (a vehicle's speed 60 s ago is still a valid feature for an ETA model).

---

## 12. Scaling Strategy

### API tier

- **Horizontal**: Kubernetes HPA scales on CPU ≥ 70 %. Adding pods requires no config change (stateless, shared Redis/DB).
- **Connection pooling**: `DB_POOL_SIZE=10` per pod. 10 pods → 100 connections, well within SQL Edge limits.
- **Rate limiting**: `slowapi` protects against abusive tenants at the application layer, before requests reach the DB.

### Worker tier

- **Horizontal**: HPA on CPU ≥ 80 %. Worker pods are fully stateless (task payloads carried in Redis/Kafka messages).
- **Queue depth**: KEDA (future roadmap) can scale on Kafka consumer lag instead of CPU, giving earlier scale-out for I/O-heavy workloads.

### Kafka

- 12 partitions on high-volume topics allows up to 12 × concurrency consumers.
- Replication factor = 3 in production (single broker in development).

---

## 13. Observability Design

### Three pillars

| Pillar | Tool | Collection |
|---|---|---|
| Metrics | Prometheus | Scrape `/metrics` every 15 s |
| Tracing | OpenTelemetry → Jaeger | `opentelemetry-sdk` auto-instrumentation |
| Logs | Structured JSON | `python-json-logger` → log aggregator |

### Key SLI metrics

```
# Error rate
rate(http_requests_total{status=~"5.."}[1m]) / rate(http_requests_total[1m])

# p99 latency
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))

# Kafka lag
kafka_consumergroup_lag_sum{consumergroup="feature-updater"}

# Celery queue depth
celery_queue_length{queue="route-optimization"}
```

### Alerting thresholds (suggested)

| Alert | Condition |
|---|---|
| High error rate | error_rate > 1 % for 5 min |
| High latency | p99 > 500 ms for 5 min |
| Kafka lag growing | lag > 10 000 for 2 min |
| Worker queue backlog | queue_length > 500 for 2 min |

---

## 14. Trade-offs and Decisions Log

| Decision | Chosen | Alternative considered | Rationale |
|---|---|---|---|
| Message broker | Kafka | RabbitMQ, AWS SQS | Kafka chosen for its ordered partitions, durable replay, and proven 10 M+ msg/sec throughput |
| ML serving | Triton (HTTP v2) | TorchServe, BentoML, inline inference | Triton supports any ONNX/TensorRT model; sub-10 ms batched GPU inference; framework-agnostic |
| Feature store | Custom (SQL + Redis) | Feast, Hopsworks | Avoid dependency on external managed service; full control over TTL and schema evolution |
| Object storage | MinIO (S3-compatible) | AWS S3, GCS | Self-hostable, S3 API compatibility means zero application change for cloud migration |
| Task queue | Celery | Dramatiq, ARQ, Temporal | Celery has the broadest ecosystem, Flower UI, and proven production usage at scale |
| Auth | JWT (RS256) | OAuth2 server, mTLS | Stateless, no token store required; RS256 allows public-key verification in downstream services |
| DB | Azure SQL Edge | PostgreSQL | Chosen for ARM64 / edge compatibility; SQLAlchemy abstraction makes migration straightforward |
