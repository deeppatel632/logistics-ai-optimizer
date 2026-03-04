<div align="center">

# Logistics AI Optimizer

**A production-grade distributed AI platform for real-time route optimization, vehicle tracking, and ML-powered logistics intelligence.**

[![CI](https://github.com/your-org/logistics-ai-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/logistics-ai-optimizer/actions/workflows/ci.yml)
[![Python 3.9](https://img.shields.io/badge/python-3.9-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [System Components](#system-components)
- [Repository Structure](#repository-structure)
- [API Endpoints](#api-endpoints)
- [Getting Started](#getting-started)
- [Deployment Guide](#deployment-guide)
- [Performance Testing](#performance-testing)
- [Monitoring](#monitoring)
- [Future Improvements](#future-improvements)

---

## Project Overview

The **Logistics AI Optimizer** is a distributed backend platform built to handle the computational demands of modern supply-chain operations at scale. The system processes real-time GPS events from a vehicle fleet, runs ML-based ETA and demand predictions in under 50 ms, and continuously re-optimizes delivery routes as traffic conditions change.

**Key capabilities:**

- Real-time vehicle tracking via Kafka event streaming (10 000+ events/sec throughput)
- Sub-50 ms ML inference using NVIDIA Triton Inference Server
- Distributed background processing with Celery + Redis (route optimization, model training)
- Multi-tenant SaaS architecture with row-level tenant isolation
- Full observability stack: Prometheus metrics + Grafana dashboards + OpenTelemetry tracing
- Production-hardened: circuit breakers, retry policies, graceful shutdown, zero-downtime deploys

---

## Architecture Overview

```
                          ┌─────────────────────────────────────────────────┐
                          │              Kubernetes Cluster                  │
                          │                                                  │
  Mobile / IoT apps ─────►│  NGINX Ingress (TLS, rate-limit, CORS)          │
  Web frontend            │        │                                         │
  Partner APIs            │        ▼                                         │
                          │  ┌─────────────┐   ┌──────────────────────────┐ │
                          │  │  FastAPI    │──►│  Kafka Event Bus          │ │
                          │  │  (2-10 pods)│   │  vehicle-location-topic   │ │
                          │  └──────┬──────┘   │  route-optimization-topic │ │
                          │         │           │  ai-prediction-topic      │ │
                          │         │           └────────────┬─────────────┘ │
                          │         │                        │                │
                          │  ┌──────▼──────┐        ┌───────▼──────────┐    │
                          │  │   Redis     │        │  Celery Workers   │    │
                          │  │  (broker +  │◄───────│  (2-8 pods, HPA) │    │
                          │  │   cache)    │        └───────┬──────────┘    │
                          │  └─────────────┘                │                │
                          │                         ┌────────┴──────────┐    │
                          │                         │                   │    │
                          │                  ┌──────▼──────┐  ┌────────▼──┐ │
                          │                  │  Feature    │  │  MinIO    │ │
                          │                  │  Store      │  │  Data     │ │
                          │                  │  (SQL+Redis)│  │  Lake     │ │
                          │                  └──────┬──────┘  └───────────┘ │
                          │                         │                        │
                          │                  ┌──────▼──────┐                 │
                          │                  │   Triton    │                 │
                          │                  │  Inference  │                 │
                          │                  │  Server     │                 │
                          │                  └─────────────┘                 │
                          │                                                  │
                          │  ┌───────────────┐   ┌─────────┐  ┌──────────┐ │
                          │  │ Azure SQL Edge│   │Prometheus│  │ Grafana  │ │
                          │  │  (primary +   │   │ metrics  │  │dashboards│ │
                          │  │   replica)    │   └─────────┘  └──────────┘ │
                          │  └───────────────┘                              │
                          └─────────────────────────────────────────────────┘
```

> For a detailed interactive diagram see [docs/architecture.md](docs/architecture.md).

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **API** | FastAPI 0.128, Python 3.9 | Async HTTP API, OpenAPI docs |
| **Database** | Azure SQL Edge, SQLAlchemy 2.0 | Primary + replica read/write split |
| **Migrations** | Alembic | Schema versioning |
| **Cache / Broker** | Redis 7 | Session cache, Celery task broker |
| **Event Streaming** | Apache Kafka (KRaft) | Real-time event bus |
| **Background Workers** | Celery 5.4, Flower | Distributed task execution |
| **ML Inference** | NVIDIA Triton Server | batched model serving < 50 ms |
| **Feature Store** | SQL + Redis (custom) | Training-serving feature parity |
| **Object Storage** | MinIO (S3-compatible) | Training data, model artefacts |
| **Observability** | Prometheus, Grafana, OpenTelemetry | Metrics, tracing, dashboards |
| **Containerisation** | Docker, Docker Compose | Local + CI environments |
| **Orchestration** | Kubernetes (k8s) | Production deployment, HPA |
| **Ingress** | NGINX Ingress + cert-manager | TLS termination, rate limiting |
| **CI/CD** | GitHub Actions | Lint, test, build, deploy |
| **Load Testing** | k6 | Performance benchmarking |

---

## Features

### Real-Time Vehicle Tracking
- Ingest GPS location events at 10 000+ events/sec via Kafka
- Per-vehicle partition key preserves event ordering
- Live vehicle speed and traffic score written to the Feature Store on every event

### Route Optimization
- Celery workers run Google OR-Tools optimization asynchronously
- Triggers issued via Kafka `route-optimization-topic`
- Results cached in Redis for sub-millisecond re-reads

### ML Inference Pipeline
- NVIDIA Triton serves `eta_model` and `demand_model` over HTTP v2
- Feature vector assembled from the Feature Store in a single SQL batch read
- Batch inference endpoint handles entire fleet predictions in one Triton call

### Multi-Tenant SaaS
- Tenant ID extracted from JWT; every SQL query filtered via SQLAlchemy event hooks
- Row-level isolation prevents cross-tenant data leakage
- Per-tenant rate limiting via slowapi

### Production Hardened
- Circuit breakers (`pybreaker`) on DB and external service calls
- Idempotency table prevents duplicate task execution on retry
- Soft-delete on all domain entities; hard audit log for every mutation
- Zero-downtime rolling deploys (`maxUnavailable: 0`) with `PodDisruptionBudget`

---

## System Components

| Component | File(s) | Description |
|---|---|---|
| API server | `backend/main.py` | FastAPI app, middleware, router registration |
| Auth | `backend/api/auth_routes.py` | JWT-based login, registration |
| Warehouses | `backend/api/warehouse_routes.py` | CRUD with tenant isolation |
| Shipments | `backend/api/shipment_routes.py` | Shipment lifecycle |
| Streaming | `backend/api/streaming_routes.py` | Kafka event ingestion endpoints |
| Workers | `backend/api/worker_routes.py` | Celery task dispatch & status |
| Kafka Producer | `backend/streaming/kafka_producer.py` | Thread-safe `publish_event()` |
| Kafka Consumer | `backend/streaming/kafka_consumer.py` | Reconnect loop, SIGTERM handling |
| Feature Store | `backend/ml/features/feature_store.py` | SQL UPSERT + Redis cache |
| Model Client | `backend/ml/models/model_client.py` | Triton HTTP v2 client, retry |
| Inference | `backend/ml/models/inference_service.py` | `predict_eta`, `batch_predict_eta` |
| Data Lake | `backend/storage/data_lake.py` | MinIO upload/download via boto3 |
| Celery App | `backend/workers/celery_app.py` | Celery configuration |
| Tasks | `backend/workers/tasks.py` | optimize_routes, run_ai_prediction |
| DB Models | `database/models.py` | SQLAlchemy ORM models |
| Config | `backend/core/config.py` | pydantic-settings, 27 fields |

---

## Repository Structure

```
logistics-ai-optimizer/
│
├── backend/                  # FastAPI application
│   ├── api/                  # Route handlers (one file per domain)
│   ├── core/                 # Config, security, middleware, metrics
│   ├── ml/
│   │   ├── features/         # Feature Store (SQL + Redis)
│   │   └── models/           # Triton model client + inference service
│   ├── services/             # Business logic (shipment, warehouse, etc.)
│   ├── storage/              # Data lake (MinIO)
│   ├── streaming/            # Kafka producer + consumer
│   └── workers/              # Celery app + task definitions
│
├── database/                 # SQLAlchemy models, connection, migrations
├── alembic/                  # Alembic migration scripts
├── k8s/                      # Kubernetes manifests (9 YAML files, 14 resources)
├── docker/                   # Dockerfiles for specialised images
├── infrastructure/
│   ├── prometheus/           # Scrape config
│   └── grafana/              # Dashboard JSON
├── load-tests/               # k6 performance test scripts
├── docs/                     # Architecture, system design, API, deployment docs
├── scripts/                  # Utility scripts (validation, ML pipeline demo)
├── tests/                    # pytest test suite (32 tests)
├── ml_engine/                # Offline training scripts
├── simulator/                # Vehicle telemetry simulator
├── monitoring/               # Prometheus config (Docker Compose target)
├── .github/workflows/        # CI (ci.yml) + CD (deploy.yml)
├── docker-compose.yml        # Development environment
├── docker-compose.prod.yml   # Production environment (10 services)
├── Dockerfile                # Multi-stage production image
└── requirements.txt          # Python dependencies
```

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | — | Register a new user |
| `POST` | `/auth/login` | — | Obtain JWT token |
| `GET` | `/health/live` | — | Liveness probe |
| `GET` | `/health/ready` | — | Readiness probe (DB + Redis check) |
| `GET` | `/warehouses/` | JWT | List tenant warehouses |
| `POST` | `/warehouses/` | JWT | Create warehouse |
| `GET` | `/warehouses/{id}` | JWT | Get warehouse by ID |
| `DELETE` | `/warehouses/{id}` | JWT | Soft-delete warehouse |
| `POST` | `/workers/optimize-route` | JWT | Dispatch route optimization task |
| `POST` | `/workers/run-ai-prediction` | JWT | Dispatch AI prediction task |
| `GET` | `/workers/task/{task_id}` | JWT | Poll Celery task status |
| `POST` | `/streaming/vehicle-location` | JWT | Publish GPS event to Kafka |
| `POST` | `/streaming/delivery-status` | JWT | Publish delivery lifecycle event |
| `POST` | `/streaming/inventory-update` | JWT | Publish stock change event |
| `POST` | `/streaming/trigger-route-optimization` | JWT | Trigger route recalculation |
| `POST` | `/streaming/trigger-ai-prediction` | JWT | Trigger ML prediction job |
| `GET` | `/audit/` | JWT | Retrieve tenant audit log |
| `GET` | `/metrics` | — | Prometheus metrics scrape endpoint |

See [docs/api.md](docs/api.md) for full request/response examples.

---

## Getting Started

### Prerequisites

- Docker Desktop ≥ 4.x
- Python 3.9+
- `kubectl` (for Kubernetes deployment)
- `k6` (for load testing)

### Local Development

```bash
# Clone the repository
git clone https://github.com/your-org/logistics-ai-optimizer.git
cd logistics-ai-optimizer

# Create virtual environment
python -m venv venv && source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment config
cp .env.prod.example .env

# Start all services
docker compose up -d

# Run database migrations
alembic upgrade head

# Start the API (hot-reload)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Run Tests

```bash
pytest -v
```

---

## Deployment Guide

See [docs/deployment.md](docs/deployment.md) for complete instructions covering:

- Single-node Docker Compose (`docker-compose.prod.yml`)
- Kubernetes deployment (`k8s/`)
- Rolling updates & zero-downtime deploys
- Scaling workers and API pods

Quick Kubernetes deploy:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml -f k8s/secrets.yaml
kubectl apply -f k8s/redis-deployment.yaml -f k8s/services.yaml
kubectl apply -f k8s/api-deployment.yaml -f k8s/celery-deployment.yaml
kubectl apply -f k8s/ingress.yaml -f k8s/hpa.yaml
```

---

## Performance Testing

Load tests are in `load-tests/k6_tests.js` using the [k6](https://k6.io/) framework.

| Scenario | VUs | Duration | Target RPS |
|---|---|---|---|
| Smoke | 10 | 30 s | baseline |
| Load | 100 | 2 min | 100 req/s |
| Stress | 500 | 3 min | 500 req/s |
| Spike | 1000 | 1 min | burst test |

```bash
# Install k6
brew install k6

# Run load test
k6 run load-tests/k6_tests.js
```

See [docs/api.md](docs/api.md) for expected performance benchmarks.

---

## Monitoring

| Dashboard | URL | Credentials |
|---|---|---|
| Grafana | http://localhost:3000 | admin / admin (change in `.env.prod`) |
| Prometheus | http://localhost:9090 | — |
| Flower (Celery) | http://localhost:5555/flower | — |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |
| FastAPI Docs | http://localhost:8000/docs | — |

Key metrics tracked:

- `http_requests_total` — API throughput by endpoint and status code
- `http_request_duration_seconds` — p50/p95/p99 latency
- `celery_queue_length` — pending tasks per queue
- `kafka_consumer_lag` — event processing backlog
- `triton_inference_latency_ms` — ML inference latency

---

## Future Improvements

| Item | Priority | Effort |
|---|---|---|
| Avro + Schema Registry for Kafka messages | High | Medium |
| KEDA queue-depth autoscaler for Celery workers | High | Low |
| GPU-enabled Triton pods for inference acceleration | Medium | Medium |
| gRPC API for internal service-to-service calls | Medium | Medium |
| A/B model routing (shadow mode, canary) | Medium | High |
| Real-time WebSocket dashboard for fleet tracking | Low | Medium |
| Drift detection pipeline for deployed models | Low | High |
| Terraform IaC for cloud infra provisioning | Low | Medium |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit: `git commit -m "feat: add my feature"`
4. Push and open a Pull Request

All PRs must pass CI (lint + 32 tests) before merge.

---

## License

MIT — see [LICENSE](LICENSE).
