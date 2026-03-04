# API Reference — Logistics AI Optimizer

**Base URL:** `http://localhost:8000`  
**Auth:** JWT Bearer token — obtain from `POST /auth/login` and include as `Authorization: Bearer <token>`.  
**Multi-tenancy:** Pass `X-Tenant-ID: <id>` header to scope all requests to a tenant.

---

## Table of Contents

1. [Authentication](#authentication)
2. [Health](#health)
3. [Warehouses](#warehouses)
4. [Shipments](#shipments)
5. [Background Jobs](#background-jobs)
6. [Streaming / Real-time Events](#streaming--real-time-events)
7. [Audit Logs](#audit-logs)
8. [Error Responses](#error-responses)
9. [Rate Limits](#rate-limits)

---

## Authentication

### POST /auth/register

Create a new user account.

**Request** — `application/x-www-form-urlencoded`

| Field | Type | Required |
|-------|------|----------|
| `username` | string | ✅ |
| `password` | string | ✅ |

**Response 200**
```json
{ "message": "User created" }
```

---

### POST /auth/login

Exchange credentials for a JWT access token.

**Request** — `application/x-www-form-urlencoded` (OAuth2 Password Grant)

| Field | Type | Required |
|-------|------|----------|
| `username` | string | ✅ |
| `password` | string | ✅ |

**Response 200**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Response 401**
```json
{ "detail": "Invalid credentials" }
```

---

## Health

### GET /health/live

Kubernetes liveness probe — always returns 200 while the process is running.

**Response 200**
```json
{ "status": "alive" }
```

---

### GET /health/ready

Kubernetes readiness probe — checks database + Redis connectivity and circuit breaker state.

**Response 200**
```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis":    "ok"
  }
}
```

**Response 503**
```json
{ "detail": "database unavailable" }
```
```json
{ "detail": "circuit open" }
```

---

### GET /metrics

Prometheus scrape endpoint (text/plain).  
Returns all registered metrics: `request_count`, `request_latency_seconds`, Celery task counters, and custom business metrics.

---

## Warehouses

All endpoints scoped by `X-Tenant-ID` header.

### POST /warehouses/

Create a warehouse.

**Request** — `application/json`
```json
{
  "name":      "London Central",
  "latitude":  51.5074,
  "longitude": -0.1278,
  "capacity":  1000
}
```

**Response 200** — `WarehouseResponse`
```json
{
  "id":        1,
  "name":      "London Central",
  "latitude":  51.5074,
  "longitude": -0.1278,
  "capacity":  1000,
  "tenant_id": 1
}
```

---

### GET /warehouses/

List all warehouses for the current tenant.

**Response 200** — array of `WarehouseResponse`
```json
[
  { "id": 1, "name": "London Central", "latitude": 51.5074, "longitude": -0.1278, "capacity": 1000, "tenant_id": 1 }
]
```

---

### GET /warehouses/{warehouse_id}

Get a single warehouse by ID.

**Response 200** — `WarehouseResponse`

**Response 404**
```json
{ "detail": "Warehouse not found" }
```

---

### DELETE /warehouses/{warehouse_id}

Soft-delete a warehouse (sets `is_deleted = true`).

**Response 200**
```json
{ "message": "Deleted successfully" }
```

**Response 404**
```json
{ "detail": "Warehouse not found" }
```

---

## Shipments

### POST /shipments/

Create a shipment (idempotent).

**Headers**

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | ✅ | `Bearer <jwt>` |
| `Idempotency-Key` | ✅ | UUID — re-submitting same key returns the cached response |

**Request** — `application/json`
```json
{
  "warehouse_id": 1,
  "product_id":   3,
  "quantity":     150
}
```

**Response 200**
```json
{
  "id":           42,
  "warehouse_id": 1,
  "product_id":   3,
  "vehicle_id":   null,
  "quantity":     150,
  "status":       "Pending",
  "tenant_id":    1
}
```

**Response 409** — duplicate Idempotency-Key
```json
{ "detail": "Duplicate request" }
```

**Rate limit:** 20 requests / minute per IP.

---

### GET /shipments/

List shipments. Supports optional `?status=InTransit` query parameter.

**Response 200** — array of shipment objects.

---

### PUT /shipments/{shipment_id}/status

Update shipment status (requires authentication).

**Query parameters**

| Param | Values |
|-------|--------|
| `new_status` | `Pending`, `InTransit`, `Delivered`, `Cancelled` |

**Response 200**
```json
{ "id": 42, "status": "InTransit", ... }
```

---

## Background Jobs

All job endpoints return immediately with a `task_id`. Poll `/jobs/task-status/{id}` for results.

### POST /jobs/optimize-route

Enqueue a Celery route optimisation task.

**Request** — `application/json`
```json
{
  "warehouse_ids": [1, 3, 7, 12],
  "constraints":   { "max_distance_km": 300 }
}
```

**Response 202**
```json
{
  "task_id": "8f14e45f-ceea-467a-a866-1234abcd5678",
  "status":  "queued",
  "queue":   "priority"
}
```

---

### POST /jobs/run-prediction

Enqueue an AI demand-forecasting / ETA task.

**Request** — `application/json`
```json
{
  "features":   { "warehouse_id": 3, "week_number": 12, "sku": "ABC-001" },
  "model_name": "demand_forecast"
}
```

**Response 202**
```json
{
  "task_id": "...",
  "status":  "queued",
  "queue":   "default"
}
```

---

### POST /jobs/run-simulation

Enqueue a long-running simulation job.

**Request** — `application/json`
```json
{
  "job_id": "sim-2026-03-04-peak-season",
  "config": { "simulation_steps": 50 }
}
```

---

### GET /jobs/task-status/{task_id}

Poll task result.

**Response 200**
```json
{
  "task_id":  "8f14e45f-ceea-467a-a866-1234abcd5678",
  "status":   "SUCCESS",
  "result":   { "optimised_route": [...], "estimated_eta_hours": 3.2 },
  "traceback": null
}
```

Possible `status` values: `PENDING`, `STARTED`, `PROGRESS`, `SUCCESS`, `FAILURE`, `REVOKED`.

---

## Streaming / Real-time Events

All streaming endpoints **publish to Kafka** and return immediately.  
Topic names: `vehicle-location-topic`, `delivery-status-topic`, `inventory-update-topic`, `iot-sensor-topic`, `route-optimization-topic`, `ai-prediction-topic`.

### POST /streaming/location

Publish a vehicle GPS update.

**Request** — `application/json`
```json
{
  "vehicle_id": "TRUCK_102",
  "latitude":   51.5074,
  "longitude":  -0.1278
}
```

**Response 200**
```json
{
  "status":    "published",
  "topic":     "vehicle-location-topic",
  "event_id":  "abc123"
}
```

---

### POST /streaming/delivery-status

Publish a delivery lifecycle event.

**Request** — `application/json`
```json
{
  "shipment_id": 42,
  "status":      "InTransit",
  "timestamp":   "2026-03-04T10:30:00Z"
}
```

---

### POST /streaming/inventory-update

Publish a warehouse stock-level change.

**Request** — `application/json`
```json
{
  "warehouse_id": 1,
  "product_id":   3,
  "delta":        -50,
  "new_quantity": 450
}
```

---

### POST /streaming/iot-sensor

Publish a raw IoT sensor reading.

**Request** — `application/json`
```json
{
  "sensor_id":  "SENSOR_007",
  "reading":    { "temp_c": 4.2, "humidity": 62 },
  "timestamp":  "2026-03-04T10:30:00Z"
}
```

---

### POST /streaming/optimize-route

Trigger async route re-optimisation via Kafka consumer.

**Request** — `application/json`
```json
{
  "vehicle_id":   "TRUCK_102",
  "warehouse_ids": [1, 5, 9]
}
```

---

### POST /streaming/ai-prediction

Trigger an async AI prediction job via Kafka consumer.

**Request** — `application/json`
```json
{
  "model_name": "demand_forecast",
  "features":   { "warehouse_id": 3, "week_number": 12 }
}
```

---

## Audit Logs

### GET /audit/

Retrieve the audit log (admin only).

**Query parameters**

| Param | Type | Description |
|-------|------|-------------|
| `skip` | int | Pagination offset (default 0) |
| `limit` | int | Page size, max 100 (default 50) |

**Response 200**
```json
[
  {
    "id":         1,
    "action":     "create_shipment",
    "entity":     "Shipment",
    "entity_id":  42,
    "user_id":    7,
    "tenant_id":  1,
    "timestamp":  "2026-03-04T10:30:00Z",
    "details":    "{ \"quantity\": 150 }"
  }
]
```

---

## Error Responses

All errors follow [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) shape:

```json
{ "detail": "<human-readable message>" }
```

| Status | Meaning |
|--------|---------|
| 400 | Bad request / validation error |
| 401 | Missing or invalid JWT |
| 403 | Insufficient permissions |
| 404 | Resource not found |
| 409 | Conflict (idempotency key duplicate) |
| 422 | Unprocessable entity (Pydantic validation failure) |
| 429 | Rate limit exceeded |
| 503 | Backend dependency unavailable |

**422 detail example:**
```json
{
  "detail": [
    {
      "loc":  ["body", "warehouse_id"],
      "msg":  "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| `POST /shipments/` | 20 / minute / IP |
| `POST /auth/login` | 10 / minute / IP |
| `POST /streaming/*` | 100 / minute / IP |
| All others | 200 / minute / IP |

On limit hit:
```json
{ "detail": "Rate limit exceeded" }
```

HTTP status: `429 Too Many Requests`

---

## Interactive Docs

FastAPI generates interactive documentation automatically:

| Interface | URL |
|-----------|-----|
| Swagger UI | <http://localhost:8000/docs> |
| ReDoc | <http://localhost:8000/redoc> |
| OpenAPI JSON | <http://localhost:8000/openapi.json> |
