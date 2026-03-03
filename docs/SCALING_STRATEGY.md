# Horizontal Scaling Strategy

## Architecture Overview

Load Balancer  
→ Multiple FastAPI Instances  
→ Azure SQL Edge  
→ Redis  
→ Background Workers  

---

## Database Pooling Strategy

Each FastAPI instance has its own SQLAlchemy engine.

Total DB connections:

instances × (pool_size + max_overflow)

Example:
3 instances
pool_size=5
max_overflow=5

Total = 30 connections

Ensure total connections remain below DB max capacity.

---

## Concurrency Safety

- Row-level locking enforced via SELECT FOR UPDATE
- Idempotency keys protected by unique constraint
- Transactions atomic via service-layer commits

Safe across multiple instances.

---

## Redis Queue Scaling

Multiple RQ workers can run simultaneously.

Workers scale horizontally.

Redis distributes jobs automatically.

---

## Production Gunicorn Recommendation

gunicorn backend.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 4 \
  --bind 0.0.0.0:8000

Adjust DB pool size based on worker count.

---

## Failure Handling

- Health checks prevent routing to unhealthy nodes
- Readiness probe detects DB/Redis failure
- Metrics monitor request latency and error rate

---

## Scaling Risks

- DB connection exhaustion
- Lock contention under high write volume
- Redis memory pressure
- Worker backlog accumulation

Mitigation via metrics monitoring and autoscaling.