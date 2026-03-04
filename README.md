<div align="center">

# Logistics AI Optimizer

**A distributed, production-grade logistics optimization platform powered by AI, real-time event streaming, and Kubernetes-native deployment.**

[![CI](https://github.com/your-org/logistics-ai-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/logistics-ai-optimizer/actions/workflows/ci.yml)
[![CD](https://github.com/your-org/logistics-ai-optimizer/actions/workflows/deploy.yml/badge.svg)](https://github.com/your-org/logistics-ai-optimizer/actions/workflows/deploy.yml)
[![Python 3.9](https://img.shields.io/badge/python-3.9-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Features](#3-features)
4. [Project Structure](#4-project-structure)
5. [Installation Guide](#5-installation-guide)
6. [Running the System](#6-running-the-system)
7. [Kubernetes Deployment](#7-kubernetes-deployment)
8. [Load Testing](#8-load-testing)
9. [CI/CD Pipeline](#9-cicd-pipeline)
10. [Future Improvements](#10-future-improvements)

---

## 1. Project Overview

The **Logistics AI Optimizer** is a distributed platform that optimizes logistics operations at scale — covering shipment lifecycle management, real-time vehicle tracking, warehouse inventory control, and AI-driven route optimization.

The system is designed from the ground up for production environments: it is multi-tenant, horizontally scalable, and hardened against common failure modes such as network partitions, duplicate message delivery, and cascading service outages.

**What it solves:**

- **Shipment delays** — ML-predicted ETAs and dynamic re-routing minimize late deliveries
- **Inventory waste** — Demand forecasting models balance stock levels across warehouses
- **Dispatcher bottlenecks** — Route optimization runs asynchronously via Celery workers, freeing operators from manual planning
- **Observability gaps** — End-to-end request tracing, Prometheus metrics, and Grafana dashboards give full visibility into system health

**Built for scale:**

| Metric | Target |
|---|---|
| Kafka event throughput | 10 000+ events / sec |
| API request latency (p95) | < 150 ms |
| ML ETA inference latency | < 50 ms |
| Celery task queue depth | ≤ 50 pending (HPA triggers above this) |
| Test coverage | 32 tests across API, inventory, and ML layers |

---

## 2. System Architecture

The platform follows a layered event-driven architecture. Synchronous API calls handle user-facing reads and writes; long-running work (route optimization, ML inference, model training) is offloaded to Celery workers via Redis. Kafka carries all real-time event streams — vehicle telemetry, delivery status changes, and inventory updates.

```
  +---------------------------------------------------------+
  |                       Clients                           |
  |          Web Dashboard . Mobile Apps . Partner APIs     |
  +---------------------------+-----------------------------+
                              |  HTTPS
                              v
  +---------------------------------------------------------+
  |                  FastAPI  (port 8000)                   |
  |  Auth . Warehouses . Shipments . Audit . Health         |
  |  TenantMiddleware . SlowAPI rate-limiter . OpenTelemetry|
  +------------+----------------------------+---------------+
               |                            |
        +------v------+             +-------v------+
        |    Redis    |             |    Kafka     |
        |  Cache +    |             |  Event Bus   |
        |  Task Broker|             |              |
        +------+------+             | * vehicle-   |
               |                   |   location   |
        +------v------------------+| * route-opt  |
        |   Celery Workers       |<| * ai-predict |
        |                        | | * delivery-  |
        | * optimize_routes      | |   status     |
        | * run_ai_prediction    | +--------------+
        | * model_training       |
        +------+-----------------+
               |
        +------v------------------+
        |   AI Route Optimizer    |
        |                         |
        | * ETA Model (R2=0.98)   |
        | * Demand Forecaster     |
        | * OR-Tools Solver       |
        +------+------------------+
               |
  +------------v--------------------------------------------+
  |                     Data Layer                          |
  |   Azure SQL Edge (primary + replica)  .  MinIO Lake     |
  |   Alembic migrations  .  SQLAlchemy 2.0 ORM             |
  +---------------------------------------------------------+

  +---------------------------------------------------------+
  |                   Observability                         |
  |   Prometheus (metrics)  .  Grafana (dashboards)        |
  |   OpenTelemetry Collector  .  Structured JSON logging  |
  +---------------------------------------------------------+
```

**Data flow — shipment creation example:**

1. Client POSTs to `POST /shipments/` with an `Idempotency-Key` header
2. FastAPI validates the JWT, resolves the tenant, and persists the shipment record
3. A Celery task `optimize_routes` is dispatched via Redis
4. The worker fetches the vehicle fleet state and calls the AI Route Optimizer
5. Optimized routes are written back to the database and cached in Redis
6. A `route-optimization-topic` Kafka event notifies downstream consumers

---

## 3. Features

### Shipment Management
Create, read, update, and soft-delete shipments with full tenant isolation. Every mutation is appended to an immutable audit log. Idempotency keys prevent duplicate creation on network retries.

### Inventory Management
Track stock levels per warehouse with real-time reads from the Feature Store (SQL + Redis). Inventory update events published to Kafka keep all service replicas in sync without polling.

### Vehicle Tracking
Ingest GPS telemetry from truck simulators via `POST /streaming/vehicle-location`. Events are published to Kafka's `vehicle-location-topic` with per-vehicle partition keys to preserve ordering. A multi-threaded truck simulator (`simulator/truck_sim.py`) generates realistic telemetry for development and load testing.

### Route Optimization
Dispatch asynchronous route-optimization jobs via `POST /workers/optimize-route`. Workers use Google OR-Tools to compute minimum-cost routes given the current vehicle positions and pending shipments. Results are cached in Redis for sub-millisecond re-reads by the dashboard.

### Real-Time Telemetry
Kafka-backed streaming endpoints accept vehicle location, delivery status, and inventory update events. The OpenTelemetry Collector receives OTLP traces from FastAPI and exports them to Prometheus for latency visibility.

### Analytics Dashboard
A Flask-powered frontend with a Chart.js analytics page (`/analytics`) renders four live charts — shipment volume, delivery performance, inventory turnover, and vehicle utilization — fed by the `/api/analytics/data` endpoint. Eight KPI cards give a summary view of operational health.

### AI Prediction System
A scikit-learn ETA model (`ml_engine/eta_model.py`) trained on generated logistics data achieves R2 = 0.98 against a held-out test set. The model predicts package arrival times from distance, cargo weight, weather severity, and traffic scores. Training scripts in `ml_engine/` serialise trained models to `ml_engine/models/` for serving.

---

## 4. Project Structure

```
logistics_ai_optimizer/
|
+-- backend/                        # FastAPI application
|   +-- main.py                     # App factory, middleware, router registration
|   +-- schemas.py                  # Pydantic request/response models
|   +-- api/                        # Route handlers - one file per domain
|   |   +-- auth_routes.py          # JWT login + registration
|   |   +-- health_routes.py        # /health/live and /health/ready probes
|   |   +-- warehouse_routes.py     # Warehouse CRUD
|   |   +-- shipment_routes.py      # Shipment lifecycle
|   |   +-- audit_routes.py         # Audit log retrieval
|   +-- core/                       # Cross-cutting concerns
|   |   +-- config.py               # pydantic-settings (27 environment fields)
|   |   +-- security.py             # JWT signing + verification
|   |   +-- tenant_middleware.py    # Multi-tenant request context injection
|   |   +-- redis_client.py         # Redis connection pool
|   |   +-- metrics.py              # Prometheus counter + histogram definitions
|   |   +-- logging_config.py       # Structured JSON logger setup
|   |   +-- db_retry.py             # Exponential back-off DB retry decorator
|   |   +-- queue.py                # Celery app + task broker configuration
|   +-- services/                   # Business logic layer
|   |   +-- shipment_service.py
|   |   +-- warehouse_service.py
|   |   +-- inventory_service.py
|   |   +-- dispatch_service.py
|   |   +-- audit_service.py
|   +-- tasks/                      # Celery task definitions
|   |   +-- shipment_tasks.py
|   +-- background/                 # Background startup routines
|   +-- ml/                         # ML integration hooks
|
+-- database/                       # Data access layer
|   +-- models.py                   # SQLAlchemy ORM models
|   +-- connection.py               # Engine, session factory, health check
|   +-- migrations/                 # Legacy migration scripts
|
+-- alembic/                        # Alembic schema migrations
|   +-- env.py
|   +-- versions/                   # 7 migration scripts
|
+-- ml_engine/                      # Offline ML training
|   +-- data_generator.py           # Synthetic logistics dataset generator
|   +-- train_eta.py                # ETA model training script
|   +-- train_dispatch.py           # Dispatch optimizer training
|   +-- train_demand.py             # Demand forecasting training
|   +-- models/                     # Serialised .pkl model artefacts
|   +-- training/                   # Training run outputs + metrics
|
+-- frontend/                       # Flask web dashboard
|   +-- app.py                      # Flask app, routes, API proxy endpoints
|   +-- templates/                  # Jinja2 HTML templates
|   +-- static/js/
|       +-- utils.js                # Shared fetch helpers + formatters
|       +-- analytics.js            # Chart.js chart initialisation
|
+-- simulator/                      # Vehicle telemetry simulator
|   +-- truck_sim.py                # Multi-threaded GPS event generator
|   +-- utils.py                    # Coordinate helpers + telemetry formatters
|
+-- tests/                          # pytest test suite
|   +-- test_api.py                 # FastAPI endpoint tests (mocked DB)
|   +-- test_inventory.py           # Inventory service unit tests
|   +-- test_ml.py                  # ML model accuracy + feature tests
|   +-- load_test.py                # Locust load test (3 user classes, 11 tasks)
|
+-- k8s/                            # Kubernetes manifests
|   +-- namespace.yaml
|   +-- configmap.yaml
|   +-- secrets.yaml
|   +-- redis-deployment.yaml
|   +-- api-deployment.yaml
|   +-- celery-deployment.yaml
|   +-- services.yaml
|   +-- ingress.yaml
|   +-- hpa.yaml                    # Horizontal Pod Autoscaler
|
+-- redis_layer/                    # Redis abstraction helpers
|   +-- cache.py
|
+-- docs/
|   +-- SCALING_STRATEGY.md
|
+-- .github/workflows/
|   +-- ci.yml                      # Test + lint on all branches
|   +-- deploy.yml                  # GHCR build + Kubernetes CD
|   +-- ci-cd.yml                   # Unified pipeline: test, build, scan, push, deploy
|
+-- docker-compose.yml              # Local dev: SQL Edge + Redis + OTEL Collector
+-- Dockerfile                      # Production image (python:3.9-slim)
+-- alembic.ini
+-- pyproject.toml                  # pytest configuration
+-- requirements.txt                # Python dependencies
```

---

## 5. Installation Guide

### Prerequisites

| Tool | Minimum version |
|---|---|
| Python | 3.9 |
| Docker Desktop | 4.x |
| kubectl | 1.28 |
| git | 2.x |

### Step 1 — Clone the repository

```bash
git clone https://github.com/your-org/logistics-ai-optimizer.git
cd logistics-ai-optimizer
```

### Step 2 — Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows
```

### Step 3 — Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4 — Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and set the required values:

```dotenv
# Database
DB_USER=sa
DB_PASSWORD=YourStrong!Passw0rd
DB_SERVER=localhost
DB_PORT=1433
DB_NAME=logistics_db

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Auth
JWT_SECRET=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=60

# App
APP_ENV=development
DEBUG=true
API_HOST=0.0.0.0
API_PORT=8000
```

### Step 5 — Start infrastructure with Docker Compose

```bash
docker compose up -d
```

This starts:
- **Azure SQL Edge** on port `1433`
- **Redis** on port `6379`
- **OpenTelemetry Collector** on ports `4317` (gRPC) and `4318` (HTTP)

### Step 6 — Run database migrations

```bash
alembic upgrade head
```

This applies all 7 migration scripts in `alembic/versions/` — creating tables for users,
tenants, shipments, warehouses, inventory, audit logs, and idempotency keys.

---

## 6. Running the System

### Start the backend API

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now available at:

| URL | Description |
|---|---|
| `http://localhost:8000/docs` | Interactive Swagger UI |
| `http://localhost:8000/redoc` | ReDoc API reference |
| `http://localhost:8000/health/live` | Liveness probe |
| `http://localhost:8000/health/ready` | Readiness probe (checks DB + Redis) |
| `http://localhost:8000/metrics` | Prometheus scrape endpoint |

### Start the frontend dashboard

Open a second terminal (with the venv activated):

```bash
python frontend/app.py
```

The Flask dashboard is now available at `http://localhost:5000`.

| Page | Route | Description |
|---|---|---|
| Dashboard | `/` | KPI summary + live shipment table |
| Analytics | `/analytics` | Chart.js charts — volume, performance, inventory, utilization |
| Vehicles | `/vehicles` | Real-time vehicle tracking map |
| Shipments | `/shipments` | Shipment management table |
| Warehouses | `/warehouses` | Warehouse inventory overview |

### Run the truck telemetry simulator

```bash
python -m simulator.truck_sim
```

Spawns configurable threads, each simulating a truck reporting GPS coordinates, speed,
fuel level, and cargo weight to the Kafka `vehicle-location-topic` at a fixed interval.

### Run tests

```bash
pytest -v
```

### Train the ETA model

```bash
python ml_engine/train_eta.py
```

Generates a synthetic logistics dataset, trains a Random Forest ETA model, evaluates it
(R2 approx 0.98), and serialises the model to `ml_engine/models/eta_model.pkl`.

---

## 7. Kubernetes Deployment

All Kubernetes manifests are in the `k8s/` directory. Apply them in dependency order:

### Step 1 — Create the namespace

```bash
kubectl apply -f k8s/namespace.yaml
```

All resources are deployed to the `logistics-ai` namespace.

### Step 2 — Apply configuration and secrets

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
```

> **Note:** Before applying `secrets.yaml`, replace the placeholder base64 values:
> ```bash
> echo -n "YourStrong!Passw0rd" | base64
> ```

### Step 3 — Deploy Redis

```bash
kubectl apply -f k8s/redis-deployment.yaml
kubectl apply -f k8s/services.yaml
```

### Step 4 — Deploy the API and Celery workers

```bash
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/celery-deployment.yaml
```

### Step 5 — Expose the API via Ingress

```bash
kubectl apply -f k8s/ingress.yaml
```

### Step 6 — Enable autoscaling

```bash
kubectl apply -f k8s/hpa.yaml
```

The Horizontal Pod Autoscaler scales the API deployment between 2 and 10 replicas
based on CPU utilization (target 60%).

### Verify deployment

```bash
kubectl get pods -n logistics-ai
kubectl get services -n logistics-ai
kubectl get ingress -n logistics-ai
```

### Rolling updates

```bash
kubectl set image deployment/logistics-api \
  api=<registry>/logistics-ai-optimizer:<new-tag> \
  -n logistics-ai

kubectl rollout status deployment/logistics-api -n logistics-ai --timeout=300s
```

### Rollback

```bash
kubectl rollout undo deployment/logistics-api -n logistics-ai
kubectl rollout undo deployment/logistics-celery -n logistics-ai
```

---

## 8. Load Testing

Load tests are written with [Locust](https://locust.io/) and located in `tests/load_test.py`.

### User classes

| Class | Description | Wait time |
|---|---|---|
| `LogisticsUser` | Balanced mix of 11 tasks (reads + writes + streaming) | 1 to 3 s |
| `ReadOnlyLogisticsUser` | Read-only subset (shipments, inventory, telemetry) | 1 to 3 s |
| `WriteHeavyLogisticsUser` | Write-intensive (create shipments, dispatch optimization) | 0.5 to 1.5 s |

### Task breakdown (`LogisticsUser`)

| Task | Weight | Endpoint |
|---|---|---|
| `get_shipments` | 4 | `GET /shipments/` |
| `get_vehicle_telemetry` | 3 | `GET /vehicles/telemetry` |
| `get_analytics_summary` | 3 | `GET /analytics/summary` |
| `get_inventory` | 2 | `GET /warehouses/{id}/inventory` |
| `create_shipment` | 1 | `POST /shipments/` (with `Idempotency-Key`) |
| `publish_vehicle_gps` | 1 | `POST /streaming/vehicle-location` |
| `publish_delivery_status` | 1 | `POST /streaming/delivery-status` |
| `publish_inventory_update` | 1 | `POST /streaming/inventory-update` |
| `dispatch_optimize_route` | 1 | `POST /workers/optimize-route` then poll task status |
| `get_audit_log` | 1 | `GET /audit/` |
| `health_check` | 1 | `GET /health/live` |

`on_start()` authenticates via `POST /auth/login` and stores the JWT for all subsequent
requests. HTTP 429 (rate-limited) and 503 (Kafka unavailable in dev) are treated as
expected results and do not count as failures.

### Running load tests

```bash
# Run with the web UI at http://localhost:8089
locust -f tests/load_test.py

# Headless — 100 users ramping over 30 s, run for 2 min
locust -f tests/load_test.py \
  --headless --users 100 --spawn-rate 10 --run-time 2m \
  --host http://localhost:8000

# Read-only scenario
locust -f tests/load_test.py ReadOnlyLogisticsUser \
  --headless --users 200 --spawn-rate 20 --run-time 3m \
  --host http://localhost:8000

# Write-heavy scenario
locust -f tests/load_test.py WriteHeavyLogisticsUser \
  --headless --users 50 --spawn-rate 5 --run-time 1m \
  --host http://localhost:8000
```

The web UI provides real-time RPS, failure rate, and response-time percentile charts.

---

## 9. CI/CD Pipeline

Three GitHub Actions workflows automate the full software delivery lifecycle.

### Workflow overview

| File | Trigger | Purpose |
|---|---|---|
| `ci.yml` | Push to any branch, PRs | Lint (flake8) + test (pytest) |
| `deploy.yml` | Push to `main`, `workflow_dispatch` | Build (GHCR) then Trivy scan then k8s deploy |
| `ci-cd.yml` | Push to `main`, PRs to `main` | **Unified 5-stage pipeline (DockerHub)** |

### `ci-cd.yml` stage breakdown

```
push to main / PR to main
        |
        v
+----------------------------+
| Stage 1 - Test             |  Python 3.9, pip install, flake8, pytest -v
|                            |  Runs on ALL triggers (PRs + main)
+------------+---------------+
             | needs: test
             v
+----------------------------+
| Stage 2 - Build            |  docker buildx (linux/amd64 + linux/arm64)
|                            |  GHA layer cache, exports image as artifact
+------------+---------------+
             | needs: build
             v
+----------------------------+
| Stage 3 - Trivy Scan       |  Loads image artifact, uploads SARIF to
|                            |  GitHub Security tab, fails on CRITICAL CVEs
+------------+---------------+
             | needs: build + scan  (main only)
             v
+----------------------------+
| Stage 4 - Push             |  Login with DOCKER_USERNAME / DOCKER_PASSWORD
|                            |  Tags: <username>/logistics-ai-optimizer:<sha>
|                            |        <username>/logistics-ai-optimizer:latest
+------------+---------------+
             | needs: push  (main only)
             v
+----------------------------+
| Stage 5 - Deploy           |  kubectl apply -f k8s/
|                            |  Rolling image update on api + celery
|                            |  Rollout wait, smoke test, auto-rollback
|                            |  Skips gracefully if KUBECONFIG is absent
+----------------------------+
```

### Required secrets

Configure these in **GitHub > Repository Settings > Secrets and Variables > Actions**:

| Secret | Required | Description |
|---|---|---|
| `DOCKER_USERNAME` | Yes (stages 4-5) | DockerHub username |
| `DOCKER_PASSWORD` | Yes (stages 4-5) | DockerHub access token |
| `KUBECONFIG` | Optional (stage 5) | Base64-encoded kubeconfig |
| `SLACK_WEBHOOK_URL` | Optional | Slack incoming webhook |

### Generating the base64 kubeconfig

```bash
# macOS
cat ~/.kube/config | base64 | pbcopy

# Linux
cat ~/.kube/config | base64
```

Paste the output as the `KUBECONFIG` secret value in GitHub.

---

## 10. Future Improvements

### ML and AI

| Improvement | Description |
|---|---|
| **ML demand forecasting** | Train LSTM/Prophet models on historical shipment data to predict weekly demand per warehouse, enabling proactive stock redistribution before shortfalls occur |
| **Real-time route optimization** | Replace the current batch OR-Tools solver with an online RL agent (PPO via Stable-Baselines3) that continuously updates routes as new GPS events arrive |
| **A/B model routing** | Deploy shadow and canary model variants behind the inference service for safe, data-driven model promotions |
| **Drift detection pipeline** | Monitor live feature distributions against training distributions using Evidently AI; trigger automated retraining on drift |

### Infrastructure and Scale

| Improvement | Description |
|---|---|
| **Global logistics simulation** | Extend the truck simulator to generate multi-country, multi-timezone fleets with realistic road networks (OpenStreetMap data) |
| **KEDA autoscaler for Celery** | Replace CPU-based HPA with KEDA keyed on Redis queue depth for true zero-to-burst scaling |
| **gRPC internal transport** | Replace HTTP calls between API and Celery result-backend with gRPC for lower overhead |
| **Terraform IaC** | Codify all cloud infrastructure as Terraform modules for one-command environment provisioning |

### Observability

| Improvement | Description |
|---|---|
| **Distributed tracing (Jaeger)** | Propagate OpenTelemetry trace context through Kafka message headers for end-to-end request tracing across API, workers, and ML inference |
| **SLO dashboards** | Define error-budget-based SLOs in Grafana (availability >= 99.9%, p95 latency <= 200 ms) with burn-rate alerts |
| **Avro + Schema Registry** | Replace plain-JSON Kafka messages with Avro validated against Confluent Schema Registry |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit using Conventional Commits: `git commit -m "feat: add my feature"`
4. Push and open a Pull Request against `main`

All PRs must pass the full `ci.yml` pipeline (lint + 32 tests) before merge.

---

## License

MIT — see [LICENSE](LICENSE).
