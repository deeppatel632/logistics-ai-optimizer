# API Reference

Base URL: `http://localhost:8000`  
Interactive docs: `http://localhost:8000/docs`  
Authentication: `Authorization: Bearer <jwt_token>`

---

## Authentication

### Register

```http
POST /auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "tenant_id": "tenant-abc"
}
```

**Response 201:**

```json
{
  "id": "usr_01J4X...",
  "email": "user@example.com",
  "tenant_id": "tenant-abc",
  "created_at": "2024-07-01T10:00:00Z"
}
```

---

### Login

```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePass123!"
}
```

**Response 200:**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

The token payload contains:

```json
{
  "sub": "usr_01J4X...",
  "tenant_id": "tenant-abc",
  "roles": ["user"],
  "exp": 1751400000
}
```

---

## Health

### Liveness probe

```http
GET /health/live
```

**Response 200:**

```json
{"status": "ok"}
```

### Readiness probe

```http
GET /health/ready
```

**Response 200:**

```json
{
  "status": "ok",
  "db": "up",
  "redis": "up"
}
```

**Response 503 (DB unavailable):**

```json
{
  "status": "degraded",
  "db": "down",
  "redis": "up"
}
```

---

## Warehouses

### Create warehouse

```http
POST /warehouses/
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "London Distribution Centre",
  "location": "51.5074,-0.1278",
  "capacity": 5000
}
```

**Response 201:**

```json
{
  "id": "wh_01J4Y...",
  "name": "London Distribution Centre",
  "location": "51.5074,-0.1278",
  "capacity": 5000,
  "tenant_id": "tenant-abc",
  "created_at": "2024-07-01T10:00:00Z"
}
```

---

### List warehouses

```http
GET /warehouses/
Authorization: Bearer <token>
```

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 100 | Page size (max 200) |

**Response 200:**

```json
[
  {
    "id": "wh_01J4Y...",
    "name": "London Distribution Centre",
    "location": "51.5074,-0.1278",
    "capacity": 5000,
    "tenant_id": "tenant-abc"
  }
]
```

---

### Get warehouse

```http
GET /warehouses/{warehouse_id}
Authorization: Bearer <token>
```

**Response 404:**

```json
{
  "detail": "Warehouse not found"
}
```

---

### Delete warehouse (soft)

```http
DELETE /warehouses/{warehouse_id}
Authorization: Bearer <token>
```

**Response 204** — No content. The record is soft-deleted (`deleted_at` is set); it does not appear in subsequent list responses.

---

## Workers (Background Tasks)

### Dispatch route optimization

```http
POST /workers/optimize-routes
Authorization: Bearer <token>
Content-Type: application/json

{
  "vehicle_ids": ["v_001", "v_002", "v_003"],
  "depot_location": "51.5074,-0.1278",
  "constraints": {
    "max_hours_per_vehicle": 8,
    "vehicle_capacity_kg": 1000
  }
}
```

**Response 202:**

```json
{
  "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "PENDING",
  "eta_seconds": 15
}
```

---

### Dispatch AI prediction

```http
POST /workers/run-ai-prediction
Authorization: Bearer <token>
Content-Type: application/json

{
  "vehicle_id": "v_001",
  "route_distance_km": 45.2
}
```

**Response 202:**

```json
{
  "task_id": "7abc1234-5717-4562-b3fc-2c963f66afa6",
  "status": "PENDING"
}
```

---

### Poll task status

```http
GET /workers/task-status/{task_id}
Authorization: Bearer <token>
```

**Response 200 (in progress):**

```json
{
  "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "PROGRESS",
  "progress": 40
}
```

**Response 200 (complete):**

```json
{
  "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "SUCCESS",
  "result": {
    "optimized_routes": [
      {
        "vehicle_id": "v_001",
        "stops": ["depot", "loc_A", "loc_B", "depot"],
        "total_distance_km": 87.4,
        "estimated_duration_hours": 2.3
      }
    ]
  }
}
```

**Response 200 (failed):**

```json
{
  "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "FAILURE",
  "error": "Redis connection timeout"
}
```

---

## Streaming (Kafka Event Ingestion)

All streaming endpoints publish to Kafka topics and return immediately. Events are processed asynchronously.

### Publish vehicle location

```http
POST /streaming/vehicle-location
Authorization: Bearer <token>
Content-Type: application/json

{
  "vehicle_id": "v_001",
  "latitude": 51.5074,
  "longitude": -0.1278,
  "speed_kmh": 62.5,
  "heading_degrees": 270,
  "timestamp": "2024-07-01T10:05:00Z"
}
```

**Response 200:**

```json
{
  "status": "published",
  "topic": "vehicle-location",
  "key": "v_001"
}
```

---

### Publish delivery status

```http
POST /streaming/delivery-status
Authorization: Bearer <token>
Content-Type: application/json

{
  "shipment_id": "shp_001",
  "vehicle_id": "v_001",
  "status": "delivered",
  "location": "51.5200,-0.1300",
  "timestamp": "2024-07-01T12:00:00Z",
  "proof_of_delivery": "base64-encoded-signature"
}
```

**Response 200:**

```json
{
  "status": "published",
  "topic": "delivery-status",
  "key": "shp_001"
}
```

---

### Publish inventory update

```http
POST /streaming/inventory-update
Authorization: Bearer <token>
Content-Type: application/json

{
  "warehouse_id": "wh_01J4Y...",
  "sku": "SKU-12345",
  "delta": -5,
  "reason": "shipment_dispatch",
  "reference_id": "shp_001"
}
```

---

### Publish IoT sensor reading

```http
POST /streaming/iot-sensor
Authorization: Bearer <token>
Content-Type: application/json

{
  "sensor_id": "sensor_truck_001_temp",
  "vehicle_id": "v_001",
  "reading_type": "temperature_celsius",
  "value": 4.2,
  "timestamp": "2024-07-01T10:05:00Z"
}
```

---

### Trigger route optimization via Kafka

```http
POST /streaming/trigger-route-optimization
Authorization: Bearer <token>
Content-Type: application/json

{
  "tenant_id": "tenant-abc",
  "vehicle_fleet": ["v_001", "v_002", "v_003"],
  "priority": "high"
}
```

Publishes to `route-optimization` Kafka topic. A Celery consumer picks up the event and runs the optimizer asynchronously.

---

### Trigger AI prediction via Kafka

```http
POST /streaming/trigger-ai-prediction
Authorization: Bearer <token>
Content-Type: application/json

{
  "prediction_type": "eta_batch",
  "vehicle_ids": ["v_001", "v_002", "v_003"],
  "route_distances_km": [45.2, 30.1, 88.9]
}
```

---

## Audit Log

### Retrieve audit log

```http
GET /audit/
Authorization: Bearer <token>
```

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 50 | Page size |
| `action` | string | — | Filter by action type |
| `user_id` | string | — | Filter by user |

**Response 200:**

```json
[
  {
    "id": "aud_001",
    "tenant_id": "tenant-abc",
    "user_id": "usr_01J4X...",
    "action": "warehouse.create",
    "entity_type": "warehouse",
    "entity_id": "wh_01J4Y...",
    "changes": {"name": "London Distribution Centre"},
    "ip_address": "192.168.1.1",
    "created_at": "2024-07-01T10:00:00Z"
  }
]
```

---

## Error Responses

All errors follow the RFC 7807 problem+json format:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning |
|---|---|
| 400 | Bad Request — invalid input, missing required fields |
| 401 | Unauthorized — missing or invalid JWT |
| 403 | Forbidden — insufficient role/permissions |
| 404 | Not Found — resource does not exist or belongs to another tenant |
| 409 | Conflict — duplicate resource or idempotency key collision |
| 422 | Unprocessable Entity — Pydantic validation failure |
| 429 | Too Many Requests — rate limit exceeded |
| 500 | Internal Server Error — unexpected server error |
| 503 | Service Unavailable — DB or dependency is down |

---

## Rate Limits

| Tier | Limit | Window |
|---|---|---|
| Default | 100 requests | 60 seconds |
| Streaming endpoints | 1 000 requests | 60 seconds |
| Auth endpoints | 20 requests | 60 seconds |

Rate limit headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1751400060
```

---

## Performance Benchmarks

Testing environment: 2× API pod (2 CPU / 4 GB), single Redis, Azure SQL Edge.

| Endpoint | p50 | p95 | p99 |
|---|---|---|---|
| `GET /health/live` | 1 ms | 3 ms | 5 ms |
| `POST /auth/login` | 45 ms | 80 ms | 120 ms |
| `GET /warehouses/` | 8 ms | 20 ms | 35 ms |
| `POST /streaming/vehicle-location` | 5 ms | 12 ms | 25 ms |
| `POST /workers/run-ai-prediction` (dispatch only) | 6 ms | 15 ms | 30 ms |
| Triton `eta_model` inference (GPU, batch=1) | 4 ms | 8 ms | 12 ms |
| Triton `eta_model` inference (GPU, batch=500) | 18 ms | 35 ms | 55 ms |
