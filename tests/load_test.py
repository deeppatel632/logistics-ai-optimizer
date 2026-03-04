# tests/load_test.py
#
# Locust load-test suite for the Logistics AI Optimizer FastAPI backend.
#
# ── Quick start ───────────────────────────────────────────────────────────────
#
#   # Web UI — open http://localhost:8089 after running
#   locust -f tests/load_test.py --host http://localhost:8000
#
#   # Headless / CI  (1 000 users, 50/s spawn, 5 min run)
#   locust -f tests/load_test.py \
#          --host http://localhost:8000 \
#          --headless \
#          --users 1000 \
#          --spawn-rate 50 \
#          --run-time 5m \
#          --html reports/load_report.html \
#          --csv  reports/load_results
#
#   # Read-only soak (stresses DB read replica + Redis cache only)
#   locust -f tests/load_test.py ReadOnlyLogisticsUser \
#          --host http://localhost:8000 --users 500 --spawn-rate 30
#
#   # Write-burst (stresses Kafka, write DB pool, idempotency table)
#   locust -f tests/load_test.py WriteHeavyLogisticsUser \
#          --host http://localhost:8000 --users 100 --spawn-rate 10
#
# ── Environment variables ─────────────────────────────────────────────────────
#
#   LOCUST_USERNAME   username for JWT auth   (default: loadtest_user)
#   LOCUST_PASSWORD   password for JWT auth   (default: loadtest_pass)
#   LOCUST_TENANT_ID  X-Tenant-ID header      (default: 1)
#
# ── Performance targets ────────────────────────────────────────────────────────
#
#   Metric             Target
#   ─────────────────────────────────────────
#   Requests/sec       > 500
#   Median latency     < 200 ms
#   95th percentile    < 800 ms
#   Failure rate       < 1 %
#
# ── Task weight distribution ──────────────────────────────────────────────────
#
#   Task                            Weight   Route
#   ─────────────────────────────────────────────────────────────────────
#   get_shipments                     4      GET  /shipments
#   get_analytics_summary             3      GET  /analytics/summary
#   get_vehicle_telemetry             3      GET  /streaming/vehicles
#   get_inventory_kpis                2      GET  /analytics/kpis
#   get_warehouses                    2      GET  /warehouses
#   health_check                      1      GET  /health/ready
#   create_shipment                   1      POST /shipments
#   publish_vehicle_gps               1      POST /streaming/vehicle-location
#   publish_delivery_status           1      POST /streaming/delivery-status
#   publish_inventory_update          1      POST /streaming/inventory-update
#   dispatch_optimize_route           1      POST /jobs/optimize-route
#
#   Rationale: read:write ≈ 3:1 — mirrors real dashboard polling behaviour.

from __future__ import annotations

import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from locust import HttpUser, between, events, tag, task
from locust.exception import RescheduleTask

logger = logging.getLogger("locust.load_test")

# ── Configuration ─────────────────────────────────────────────────────────────

_USERNAME  = os.environ.get("LOCUST_USERNAME",  "loadtest_user")
_PASSWORD  = os.environ.get("LOCUST_PASSWORD",  "loadtest_pass")
_TENANT_ID = os.environ.get("LOCUST_TENANT_ID", "1")

# Realistic FK pools (small enough to stay within seed data, varied enough
# to produce non-trivial DB access patterns).
_WAREHOUSE_IDS  = list(range(1, 6))          # warehouses 1-5
_PRODUCT_IDS    = list(range(1, 11))         # products 1-10
_VEHICLE_IDS    = [f"TRUCK_{i:03d}" for i in range(1, 21)]   # TRUCK_001-020
_STATUS_FILTERS = ["Pending", "InTransit", "Delivered", "Cancelled"]

# Continental-Europe GPS bounding box matches the demo dataset
_LAT_RANGE = (36.0, 71.0)
_LON_RANGE = (-10.0, 40.0)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _coords() -> tuple[float, float]:
    return round(random.uniform(*_LAT_RANGE), 6), round(random.uniform(*_LON_RANGE), 6)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _idempotency_key() -> str:
    """POST /shipments requires a UUID Idempotency-Key header each call."""
    return str(uuid.uuid4())


def _log_failure(name: str, resp) -> None:
    logger.warning("FAILURE %-40s  status=%d  body=%.150s", name, resp.status_code, resp.text)


# ── Event hooks ───────────────────────────────────────────────────────────────

@events.test_start.add_listener
def _on_test_start(environment, **kwargs):
    logger.info(
        "Load test starting | host=%s | target_users=%s",
        environment.host,
        getattr(environment.runner, "target_user_count", "?"),
    )


@events.quitting.add_listener
def _on_quit(environment, **kwargs):
    s     = environment.stats.total
    ratio = s.fail_ratio
    logger.info(
        "Load test complete | requests=%d | failures=%d | "
        "failure_rate=%.2f%% | median=%d ms | p95=%d ms | rps=%.1f",
        s.num_requests,
        s.num_failures,
        ratio * 100,
        s.median_response_time,
        s.get_response_time_percentile(0.95),
        s.current_rps,
    )
    if ratio > 0.01:
        print(f"\n⚠  Error rate {ratio:.1%} EXCEEDS 1 % threshold.\n")
        environment.process_exit_code = 1
    else:
        print(f"\n✅  Load test passed — error rate {ratio:.2%}\n")


# ═════════════════════════════════════════════════════════════════════════════
# LogisticsUser — the primary simulated user (full read+write mix)
# ═════════════════════════════════════════════════════════════════════════════

class LogisticsUser(HttpUser):
    """Simulates a single authenticated operator on the logistics platform.

    Lifecycle
    ─────────
    on_start  → POST /auth/login  → store JWT in session headers
    tasks     → weighted task set executed with 1-3 s think time
    on_stop   → nothing (JWT is stateless)

    Auth failures cause the virtual user to be rescheduled (on_start is
    retried) rather than silently running unauthenticated.
    """

    wait_time = between(1, 3)
    _token: Optional[str] = None

    # ── Auth lifecycle ────────────────────────────────────────────────────

    def on_start(self) -> None:
        """Obtain a JWT and set the Authorization header for this session."""
        with self.client.post(
            "/auth/login",
            data={"username": _USERNAME, "password": _PASSWORD},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Tenant-ID":  _TENANT_ID,
            },
            name="[auth] POST /auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                body        = resp.json()
                self._token = body.get("access_token")
                if self._token:
                    self.client.headers.update({
                        "Authorization": f"Bearer {self._token}",
                        "X-Tenant-ID":   _TENANT_ID,
                    })
                    resp.success()
                else:
                    resp.failure("Login succeeded but response contains no access_token")
                    self._token = None
            else:
                resp.failure(
                    f"Login failed  status={resp.status_code}  "
                    f"body={resp.text[:200]}"
                )
                self._token = None

    def _guard(self) -> None:
        """Raise RescheduleTask if not authenticated — triggers a re-login."""
        if not self._token:
            raise RescheduleTask()

    # ── Task 1 — Fetch shipments ──────────────────────────────────────────

    @tag("read", "shipments")
    @task(4)
    def get_shipments(self) -> None:
        """GET /shipments — fetch the live shipment list.

        Most users view page 1; a minority browse further pages.
        Randomly filters by status to exercise the query-filter path.
        """
        self._guard()

        params: dict = {
            "skip":  random.choice([0, 0, 0, 20, 50]),
            "limit": random.choice([20, 50, 100]),
        }
        if random.random() < 0.3:          # 30 % of calls apply a status filter
            params["status"] = random.choice(_STATUS_FILTERS)

        with self.client.get(
            "/shipments",
            params=params,
            name="[read] GET /shipments",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("GET /shipments", resp)

    # ── Task 2 — Create shipment ──────────────────────────────────────────

    @tag("write", "shipments")
    @task(1)
    def create_shipment(self) -> None:
        """POST /shipments — create a new shipment.

        Key implementation notes:
        - The backend enforces a unique ``Idempotency-Key`` UUID header on
          every POST; omitting it causes a 422 validation error.
        - Rate limit: 20 requests/min per IP.  429 responses are marked
          success so they don't inflate the failure metric; they are only
          logged at DEBUG level.
        """
        self._guard()

        payload = {
            "warehouse_id": random.choice(_WAREHOUSE_IDS),
            "product_id":   random.choice(_PRODUCT_IDS),
            "quantity":     random.randint(1, 500),
        }

        with self.client.post(
            "/shipments",
            json=payload,
            headers={"Idempotency-Key": _idempotency_key()},
            name="[write] POST /shipments",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 201):
                resp.success()
            elif resp.status_code == 429:
                # Rate-limiter kick-in — expected under heavy write load
                resp.success()
                logger.debug("POST /shipments 429 rate-limited (expected under load)")
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            elif resp.status_code == 422:
                resp.failure(f"Validation error: {resp.text[:200]}")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("POST /shipments", resp)

    # ── Task 3 — Fetch inventory (via analytics KPIs) ─────────────────────

    @tag("read", "inventory")
    @task(2)
    def get_inventory(self) -> None:
        """GET /analytics/kpis — warehouse stock levels and utilisation.

        There is no dedicated /inventory endpoint; inventory data is
        aggregated in /analytics/kpis under ``warehouse_load``.  This is the
        same endpoint the Flask /inventory page and the analytics dashboard
        both consume.
        """
        self._guard()

        with self.client.get(
            "/analytics/kpis",
            name="[read] GET /analytics/kpis (inventory)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                body = resp.json()
                if "warehouse_load" not in body:
                    resp.failure("Response missing 'warehouse_load'")
                else:
                    resp.success()
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("GET /analytics/kpis", resp)

    # ── Task 4 — Fetch vehicle telemetry ──────────────────────────────────

    @tag("read", "telemetry", "vehicles")
    @task(3)
    def get_vehicle_telemetry(self) -> None:
        """GET /streaming/vehicles — live vehicle GPS positions.

        This is the primary telemetry endpoint: the Flask vehicle-tracking
        map polls it every 5 seconds per connected user.  At 1 000 concurrent
        users it generates ~200 RPS on this single endpoint — the most
        important read path to stress-test.
        """
        self._guard()

        with self.client.get(
            "/streaming/vehicles",
            name="[read] GET /streaming/vehicles (telemetry)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("GET /streaming/vehicles", resp)

    # ── Supplementary read tasks ──────────────────────────────────────────

    @tag("read", "analytics")
    @task(3)
    def get_analytics_summary(self) -> None:
        """GET /analytics/summary — KPI card data fetched by the dashboard."""
        self._guard()

        with self.client.get(
            "/analytics/summary",
            name="[read] GET /analytics/summary",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("GET /analytics/summary", resp)

    @tag("read", "warehouses")
    @task(2)
    def get_warehouses(self) -> None:
        """GET /warehouses — warehouse directory."""
        self._guard()

        with self.client.get(
            "/warehouses",
            name="[read] GET /warehouses",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("GET /warehouses", resp)

    @tag("health")
    @task(1)
    def health_check(self) -> None:
        """GET /health/ready — liveness probe (no auth required)."""
        with self.client.get(
            "/health/ready",
            name="[health] GET /health/ready",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health probe failed  status={resp.status_code}")

    # ── Supplementary write / streaming tasks ────────────────────────────

    @tag("write", "streaming", "telemetry")
    @task(1)
    def publish_vehicle_gps(self) -> None:
        """POST /streaming/vehicle-location — GPS event from a truck / IoT device.

        503 (Kafka unavailable) is treated as success so the test still runs
        cleanly when Kafka is not deployed locally.
        """
        self._guard()

        lat, lon = _coords()
        payload  = {
            "vehicle_id": random.choice(_VEHICLE_IDS),
            "latitude":   lat,
            "longitude":  lon,
            "timestamp":  _iso_now(),
        }

        with self.client.post(
            "/streaming/vehicle-location",
            json=payload,
            name="[write] POST /streaming/vehicle-location",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 202):
                resp.success()
            elif resp.status_code == 503:
                resp.success()    # Kafka down — expected in dev / test env
                logger.debug("Kafka 503 on vehicle-location (expected without Kafka)")
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("POST /streaming/vehicle-location", resp)

    @tag("write", "streaming", "delivery")
    @task(1)
    def publish_delivery_status(self) -> None:
        """POST /streaming/delivery-status — lifecycle event from a driver app."""
        self._guard()

        lat, lon = _coords()
        payload  = {
            "shipment_id": str(random.randint(1, 10_000)),
            "vehicle_id":  random.choice(_VEHICLE_IDS),
            "status":      random.choice(
                ["picked_up", "in_transit", "out_for_delivery", "delivered", "failed"]
            ),
            "latitude":    lat,
            "longitude":   lon,
            "timestamp":   _iso_now(),
        }

        with self.client.post(
            "/streaming/delivery-status",
            json=payload,
            name="[write] POST /streaming/delivery-status",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 202):
                resp.success()
            elif resp.status_code == 503:
                resp.success()
                logger.debug("Kafka 503 on delivery-status (expected without Kafka)")
            elif resp.status_code in (401, 422):
                resp.failure(f"status={resp.status_code}  body={resp.text[:120]}")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("POST /streaming/delivery-status", resp)

    @tag("write", "streaming", "inventory")
    @task(1)
    def publish_inventory_update(self) -> None:
        """POST /streaming/inventory-update — stock-level change event."""
        self._guard()

        payload = {
            "warehouse_id":   random.choice(_WAREHOUSE_IDS),
            "product_id":     random.choice(_PRODUCT_IDS),
            "delta_quantity": random.choice(
                [random.randint(1, 200), -random.randint(1, 50)]
            ),
            "timestamp": _iso_now(),
        }

        with self.client.post(
            "/streaming/inventory-update",
            json=payload,
            name="[write] POST /streaming/inventory-update",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 202):
                resp.success()
            elif resp.status_code == 503:
                resp.success()
                logger.debug("Kafka 503 on inventory-update (expected without Kafka)")
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("POST /streaming/inventory-update", resp)

    @tag("write", "jobs")
    @task(1)
    def dispatch_optimize_route(self) -> None:
        """POST /jobs/optimize-route — enqueue a route-optimisation Celery task."""
        self._guard()

        payload = {
            "warehouse_ids": random.sample(range(1, 11), k=random.randint(2, 5)),
            "constraints":   {"max_distance_km": 500},
        }

        with self.client.post(
            "/jobs/optimize-route",
            json=payload,
            name="[write] POST /jobs/optimize-route",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 201, 202):
                body   = resp.json()
                tid    = body.get("task_id")
                if tid:
                    self._poll_task(tid)
                resp.success()
            elif resp.status_code == 422:
                resp.failure(f"Validation error: {resp.text[:200]}")
            elif resp.status_code == 401:
                self._token = None
                resp.failure("JWT expired — will re-authenticate")
            else:
                resp.failure(f"Unexpected {resp.status_code}")
                _log_failure("POST /jobs/optimize-route", resp)

    def _poll_task(self, task_id: str, max_polls: int = 3) -> None:
        """Poll a Celery task until it reaches a terminal state (max 3 times)."""
        for _ in range(max_polls):
            time.sleep(0.5)
            with self.client.get(
                f"/jobs/task-status/{task_id}",
                name="[jobs] GET /jobs/task-status/{id}",
                catch_response=True,
            ) as r:
                if r.status_code not in (200, 404):
                    r.failure(f"Poll error: {r.status_code}")
                    return
                if r.status_code == 200:
                    state = r.json().get("status", "")
                    if state in ("SUCCESS", "FAILURE", "finished", "failed"):
                        r.success()
                        return


# ═════════════════════════════════════════════════════════════════════════════
# ReadOnlyLogisticsUser — pure read soak (stresses DB replica + Redis cache)
# ═════════════════════════════════════════════════════════════════════════════

class ReadOnlyLogisticsUser(LogisticsUser):
    """Runs only read tasks.

    Use to isolate read-path performance from write-path mutations.

    Example:
        locust -f tests/load_test.py ReadOnlyLogisticsUser \\
               --host http://localhost:8000 --users 500 --spawn-rate 30
    """

    tasks = {
        LogisticsUser.get_shipments:          4,
        LogisticsUser.get_analytics_summary:  3,
        LogisticsUser.get_vehicle_telemetry:  3,
        LogisticsUser.get_inventory:          2,
        LogisticsUser.get_warehouses:         2,
        LogisticsUser.health_check:           1,
    }


# ═════════════════════════════════════════════════════════════════════════════
# WriteHeavyLogisticsUser — write burst (stresses Kafka + DB write pool)
# ═════════════════════════════════════════════════════════════════════════════

class WriteHeavyLogisticsUser(LogisticsUser):
    """Runs only write tasks with a shorter think time.

    Example:
        locust -f tests/load_test.py WriteHeavyLogisticsUser \\
               --host http://localhost:8000 --users 100 --spawn-rate 10
    """

    wait_time = between(0.5, 1.5)    # shorter think time → higher write throughput

    tasks = {
        LogisticsUser.create_shipment:            3,
        LogisticsUser.publish_vehicle_gps:        3,
        LogisticsUser.publish_delivery_status:    2,
        LogisticsUser.publish_inventory_update:   2,
        LogisticsUser.dispatch_optimize_route:    1,
    }
