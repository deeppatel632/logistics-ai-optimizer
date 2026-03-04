# Deployment Guide — Logistics AI Optimizer

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Variables](#environment-variables)
3. [Local Development](#local-development)
4. [Docker Compose (Production Stack)](#docker-compose-production-stack)
5. [Database Migrations](#database-migrations)
6. [Kubernetes Deployment](#kubernetes-deployment)
7. [Health Checks & Smoke Tests](#health-checks--smoke-tests)
8. [Rolling Updates & Rollback](#rolling-updates--rollback)
9. [Observability Stack](#observability-stack)
10. [Running the Flask Dashboard](#running-the-flask-dashboard)
11. [Running the Truck Simulator](#running-the-truck-simulator)
12. [Load Testing](#load-testing)

---

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| Docker | 24.x | Container runtime |
| Docker Compose | 2.20 | Local multi-service stack |
| Python | 3.9+ | Backend + simulator |
| kubectl | 1.28+ | Kubernetes management |
| Helm | 3.x | Optional chart management |
| k6 | 0.49+ | Load testing (alternative to Locust) |

---

## Environment Variables

Copy `.env.example` to `.env` and populate every field:

```env
# ── App ─────────────────────────────────────────────────────────────
APP_ENV=production
DEBUG=false
API_HOST=0.0.0.0
API_PORT=8000

# ── Database (Azure SQL Edge) ───────────────────────────────────────
DB_USER=sa
DB_PASSWORD=YourStrong!Passw0rd
DB_SERVER=db
DB_PORT=1433
DB_NAME=logistics_db
DB_DRIVER=ODBC+Driver+17+for+SQL+Server
PRIMARY_DB_URL=mssql+pyodbc://sa:YourStrong!Passw0rd@db:1433/logistics_db?driver=ODBC+Driver+17+for+SQL+Server
REPLICA_DB_URL=mssql+pyodbc://sa:YourStrong!Passw0rd@db:1433/logistics_db?driver=ODBC+Driver+17+for+SQL+Server
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800

# ── Redis ───────────────────────────────────────────────────────────
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# ── JWT ────────────────────────────────────────────────────────────
JWT_SECRET=change-me-to-a-long-random-string
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=60

# ── Kafka ──────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP_SERVERS=kafka:9092

# ── ML / Triton ────────────────────────────────────────────────────
TRITON_BASE_URL=http://triton:8000

# ── MinIO ──────────────────────────────────────────────────────────
MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=logistics-data-lake
MINIO_USE_SSL=false

# ── Flask Dashboard ────────────────────────────────────────────────
FASTAPI_BASE_URL=http://api:8000
FLASK_SECRET_KEY=change-me-dashboard-secret
FLASK_PORT=5050
```

---

## Local Development

### 1. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 2. Start infrastructure services only

```bash
docker compose -f docker-compose.prod.yml up -d db redis kafka
```

### 3. Run Alembic migrations

```bash
alembic upgrade head
```

### 4. Start FastAPI

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Start Celery worker (separate terminal)

```bash
celery -A backend.workers.celery_app worker --loglevel=info -Q default,priority,bulk
```

### 6. Start Flask dashboard (separate terminal)

```bash
FASTAPI_BASE_URL=http://localhost:8000 python -m frontend.app
```

Open: <http://localhost:5050>

---

## Docker Compose (Production Stack)

The full 12-service stack:

```bash
# Build and start all services
docker compose -f docker-compose.prod.yml up --build -d

# View logs
docker compose -f docker-compose.prod.yml logs -f api

# Stop all services
docker compose -f docker-compose.prod.yml down
```

### Service map

| Service | Port | Description |
|---------|------|-------------|
| `api` | 8000 | FastAPI backend |
| `celery` | — | Background workers |
| `flower` | 5555 | Celery monitoring UI |
| `db` | 1433 | Azure SQL Edge |
| `redis` | 6379 | Cache + broker |
| `kafka` | 9092 | Event streaming |
| `triton` | 8000/8001/8002 | ML inference server |
| `minio` | 9000/9001 | Object storage |
| `prometheus` | 9090 | Metrics collection |
| `grafana` | 3000 | Dashboards (admin/admin) |
| `dashboard` | 5050 | Flask frontend |
| `simulator` | — | Truck GPS simulator |

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "add_xyz_table"

# Rollback one step
alembic downgrade -1

# View migration history
alembic history --verbose
```

Tables created by migrations:

| Migration | Content |
|-----------|---------|
| `d179ecaaf754` | Initial schema (Vehicle, Warehouse, Product, Shipment, Inventory) |
| `8d1dc120a74e` | Users table |
| `8fe3f4d12f66` | Multi-tenant Tenant table |
| `cfd129a30f7c` | tenant_id FK on User |
| `890587bd43df` | Idempotency keys |
| `4ee8f463b611` | Soft-delete fields |
| `19cc9c84910d` | Audit logs |

---

## Kubernetes Deployment

### Namespace and secrets

```bash
# Create namespace
kubectl create namespace logistics-ai

# Database + Redis secrets
kubectl create secret generic logistics-secrets \
  --from-literal=DB_PASSWORD='YourStrong!Passw0rd' \
  --from-literal=JWT_SECRET='your-jwt-secret' \
  --from-literal=REDIS_PASSWORD='' \
  -n logistics-ai

# Docker registry secret (GitHub Container Registry)
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=YOUR_GITHUB_USERNAME \
  --docker-password=YOUR_GITHUB_TOKEN \
  -n logistics-ai
```

### Apply manifests (ordered)

```bash
# 1 — Storage
kubectl apply -f k8s/redis-deployment.yml       -n logistics-ai
kubectl apply -f k8s/kafka-deployment.yml        -n logistics-ai

# 2 — Database
kubectl apply -f k8s/db-deployment.yml           -n logistics-ai

# Wait for DB readiness
kubectl rollout status deployment/db -n logistics-ai

# 3 — Run migrations (Job)
kubectl apply -f k8s/migration-job.yml           -n logistics-ai

# 4 — Application tier
kubectl apply -f k8s/api-deployment.yml          -n logistics-ai
kubectl apply -f k8s/celery-deployment.yml        -n logistics-ai

# 5 — HPA
kubectl apply -f k8s/api-hpa.yml                 -n logistics-ai
kubectl apply -f k8s/celery-hpa.yml              -n logistics-ai

# 6 — Ingress
kubectl apply -f k8s/ingress.yml                 -n logistics-ai
```

### Verify deployment

```bash
kubectl get pods     -n logistics-ai
kubectl get svc      -n logistics-ai
kubectl get hpa      -n logistics-ai
kubectl get ingress  -n logistics-ai
```

---

## Health Checks & Smoke Tests

```bash
# Liveness
curl http://localhost:8000/health/live
# → {"status":"alive"}

# Readiness (requires DB + Redis up)
curl http://localhost:8000/health/ready
# → {"status":"ready","checks":{"database":"ok","redis":"ok"}}

# Metrics endpoint
curl http://localhost:8000/metrics
```

---

## Rolling Updates & Rollback

```bash
# Trigger rolling update (CI/CD style)
kubectl set image deployment/api app=ghcr.io/YOUR_ORG/logistics-ai:NEW_TAG -n logistics-ai

# Watch rollout
kubectl rollout status deployment/api -n logistics-ai

# Rollback on failure
kubectl rollout undo deployment/api -n logistics-ai

# View rollout history
kubectl rollout history deployment/api -n logistics-ai
```

---

## Observability Stack

| Service | URL | Credentials |
|---------|-----|-------------|
| Prometheus | <http://localhost:9090> | none |
| Grafana | <http://localhost:3000> | admin / admin |
| Flower (Celery) | <http://localhost:5555> | none |
| MinIO Console | <http://localhost:9001> | minioadmin / minioadmin |

Import the pre-built dashboard:
`infrastructure/grafana/dashboard.json` → Grafana → Dashboards → Import

---

## Running the Flask Dashboard

```bash
# Development
FASTAPI_BASE_URL=http://localhost:8000 \
FLASK_SECRET_KEY=dev-secret \
python -m frontend.app

# Production (via gunicorn)
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5050 "frontend.app:app"
```

Login with any credentials registered in FastAPI (`POST /auth/register`).

---

## Running the Truck Simulator

```bash
# Simulate GPS telemetry against local backend
SIM_TOKEN=<JWT_TOKEN> \
FASTAPI_BASE_URL=http://localhost:8000 \
TELEMETRY_INTERVAL_S=5 \
SIM_SPEED_KMPH=80 \
python -m simulator.truck_sim
```

The simulator:
1. Polls `/shipments?status=InTransit` on startup
2. Generates a GPS path from origin to destination warehouse
3. POSTs location updates to `/streaming/location` every 5 seconds
4. Marks shipments `Delivered` on arrival (within 500 m)

---

## Load Testing

### Locust (web UI)

```bash
pip install locust
locust -f tests/load_test.py --host http://localhost:8000
# Open http://localhost:8089 → set 1000 users, 50 spawn/s
```

### Locust (headless / CI)

```bash
locust -f tests/load_test.py \
  --headless \
  --users 1000 \
  --spawn-rate 50 \
  --run-time 2m \
  --host http://localhost:8000 \
  --html tests/load_report.html
```

Pass/fail gate: test exits with code 1 if error rate > 1%.

### k6 (alternative)

```bash
k6 run --env SCENARIO=load load-tests/k6_tests.js
```

Thresholds: `p95 < 500ms`, `error_rate < 1%`.
