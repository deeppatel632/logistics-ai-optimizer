# Deployment Guide

This guide covers local development, production Docker Compose, and Kubernetes deployment.

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Docker | ≥ 24.x | Container runtime |
| Docker Compose | ≥ 2.x | Multi-service orchestration |
| Python | 3.9 | Local development |
| kubectl | ≥ 1.28 | Kubernetes CLI |
| Helm | ≥ 3.x | Kubernetes package manager (optional) |
| k6 | ≥ 0.49 | Load testing |

---

## Environment Configuration

```bash
# Copy the example file
cp .env.prod.example .env

# Required fields (minimum set for local dev)
APP_ENV=development
DEBUG=true
DB_USER=sa
DB_PASSWORD=YourStrong!Passw0rd
DB_SERVER=sql_edge
DB_PORT=1433
DB_NAME=logistics_db
DB_DRIVER=ODBC+Driver+18+for+SQL+Server
JWT_SECRET=change-me-to-a-secure-random-string
REDIS_HOST=redis
REDIS_PORT=6379
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
TRITON_BASE_URL=http://triton:8000
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=logistics-ai-data
MINIO_USE_SSL=false
```

---

## Local Development

### 1. Start infrastructure services

```bash
docker compose up -d sql_edge redis kafka
```

Wait for SQL Edge to be healthy (~ 30 s):

```bash
docker compose ps
```

### 2. Install Python dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Run database migrations

```bash
alembic upgrade head
```

### 4. Start the API with hot-reload

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Start a Celery worker (optional)

```bash
celery -A backend.workers.celery_app worker --loglevel=info --queues=default,route-optimization,ai-prediction
```

### 6. Access services

| Service | URL |
|---|---|
| FastAPI docs | http://localhost:8000/docs |
| Prometheus metrics | http://localhost:8000/metrics |

---

## Production — Docker Compose

The `docker-compose.prod.yml` file runs all 10 services:

| Service | Port(s) | Description |
|---|---|---|
| `sql_edge` | 1433 | Azure SQL Edge (primary DB) |
| `redis` | 6379 | Redis 7 (cache + broker) |
| `api` | 8000 | FastAPI application |
| `celery_worker` | — | Celery background workers |
| `celery_flower` | 5555 | Flower monitoring UI |
| `kafka` | 9092 | Apache Kafka (KRaft) |
| `minio` | 9000, 9001 | MinIO object storage |
| `triton` | 8001–8003 | NVIDIA Triton Inference Server |
| `prometheus` | 9090 | Prometheus metrics |
| `grafana` | 3000 | Grafana dashboards |
| `otel_collector` | 4317, 4318 | OpenTelemetry Collector |

```bash
# Build and start all services
docker compose -f docker-compose.prod.yml up -d --build

# Check status
docker compose -f docker-compose.prod.yml ps

# Run migrations against production DB
docker compose -f docker-compose.prod.yml exec api alembic upgrade head

# View API logs
docker compose -f docker-compose.prod.yml logs -f api

# Scale workers
docker compose -f docker-compose.prod.yml up -d --scale celery_worker=4
```

### Creating the MinIO bucket

```bash
docker compose -f docker-compose.prod.yml exec api python scripts/ml_pipeline_example.py
# This calls create_bucket_if_missing() on startup
```

---

## Kubernetes Deployment

### Cluster requirements

- Kubernetes ≥ 1.28
- NGINX Ingress Controller
- cert-manager (for TLS)
- Persistent Volume provisioner (for Redis StatefulSet)
- At least 3 worker nodes (2 CPU / 4 GB RAM each)

### Apply manifests in order

```bash
# 1. Namespace
kubectl apply -f k8s/namespace.yaml

# 2. Config and secrets
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml

# 3. Stateful services (Redis)
kubectl apply -f k8s/redis-deployment.yaml

# 4. Application deployments
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/celery-deployment.yaml

# 5. Services
kubectl apply -f k8s/services.yaml

# 6. Ingress + TLS
kubectl apply -f k8s/ingress.yaml

# 7. Autoscaling
kubectl apply -f k8s/hpa.yaml

# Verify everything is running
kubectl get all -n logistics-ai
```

### Verify deployments

```bash
# API pods
kubectl get pods -n logistics-ai -l app=logistics-api

# HPA status
kubectl describe hpa -n logistics-ai

# Check Ingress
kubectl get ingress -n logistics-ai
```

### Rolling update (zero-downtime)

The API deployment is configured with:

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 0
    maxSurge: 1
```

To trigger a rolling update after pushing a new image:

```bash
kubectl set image deployment/logistics-api \
  api=ghcr.io/your-org/logistics-ai-optimizer:v2.0.0 \
  -n logistics-ai

# Watch rollout progress
kubectl rollout status deployment/logistics-api -n logistics-ai

# Roll back if needed
kubectl rollout undo deployment/logistics-api -n logistics-ai
```

---

## Secrets Management

### Kubernetes secrets (base64 encoded)

```bash
# Create secrets from .env.prod file
kubectl create secret generic logistics-secrets \
  --from-env-file=.env.prod \
  -n logistics-ai

# Or from literal values
kubectl create secret generic logistics-secrets \
  --from-literal=DB_PASSWORD='YourStrong!Passw0rd' \
  --from-literal=JWT_SECRET='your-jwt-secret' \
  -n logistics-ai
```

> **Production note**: Use an external secret manager (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault) and inject via External Secrets Operator. Never commit raw secrets to the repository.

---

## Database Migrations in Production

```bash
# Run via Kubernetes Job
kubectl exec -it deployment/logistics-api -n logistics-ai -- alembic upgrade head

# Or as a one-off Kubernetes Job before deployment
kubectl apply -f k8s/migrations-job.yaml
```

---

## Monitoring Setup

### Prometheus

Prometheus is configured to scrape all services at 15-second intervals. The configuration is in `infrastructure/prometheus/prometheus.yml`. Import it when starting Prometheus.

### Grafana

1. Open Grafana at http://localhost:3000 (default credentials: `admin/admin`)
2. Add Prometheus data source: `http://prometheus:9090`
3. Import `infrastructure/grafana/dashboard.json` (Dashboard ID: custom)
4. Set the dashboard's data source to your Prometheus instance

---

## Scaling Guide

### Scale API pods manually

```bash
kubectl scale deployment logistics-api --replicas=5 -n logistics-ai
```

### Scale Celery workers

```bash
# Kubernetes
kubectl scale deployment logistics-celery --replicas=6 -n logistics-ai

# Docker Compose
docker compose -f docker-compose.prod.yml up -d --scale celery_worker=6
```

### Adjust HPA thresholds

```bash
kubectl patch hpa logistics-api-hpa -n logistics-ai \
  --patch '{"spec":{"targetCPUUtilizationPercentage":60}}'
```

---

## Health Checks

| Endpoint | Purpose | Expected response |
|---|---|---|
| `GET /health/live` | Kubernetes liveness probe | `{"status": "ok"}` |
| `GET /health/ready` | Kubernetes readiness probe | `{"status": "ok", "db": "up", "redis": "up"}` |
| `GET /metrics` | Prometheus scrape | Prometheus exposition format |

---

## CI/CD Pipeline

The GitHub Actions pipeline (`.github/workflows/deploy.yml`) runs on every push to `main`:

1. **Test** — `pytest -v` + `flake8` (all 32 tests must pass)
2. **Build** — Docker multi-stage build, push to `ghcr.io`
3. **Deploy** — `kubectl set image` rolling update on the production cluster

See `.github/workflows/deploy.yml` for the full pipeline configuration.
