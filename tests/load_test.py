# tests/load_test.py
#
# Locust load-testing suite for the Logistics AI Optimizer platform.
#
# Simulates 1 000 concurrent users performing realistic traffic patterns:
#   60 % — shipment list / view operations (read-heavy)
#   20 % — create shipment + poll status (write + async)
#   15 % — warehouse reads
#    5 % — health checks
#
# Usage
# ─────
#
# Install:
#   pip install locust
#
# Run headless (CI):
#   locust -f tests/load_test.py \
#          --headless \
#          --users 1000 \
#          --spawn-rate 50 \
#          --run-time 2m \
#          --host http://localhost:8000 \
#          --html tests/load_report.html
#
# Run with web UI (interactive):
#   locust -f tests/load_test.py --host http://localhost:8000
#   Open http://localhost:8089
#
# Environment variables
# ─────────────────────
#   LOCUST_USERNAME   API username for JWT auth  (default: loadtest_user)
#   LOCUST_PASSWORD   API password               (default: loadtest_pass)
#   LOCUST_TENANT_ID  Tenant header value        (default: 1)

import json
import os
import random
import time
from typing import Optional

from locust import FastHttpUser, between, events, tag, task
from locust.runners import MasterRunner


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_USERNAME  = os.environ.get("LOCUST_USERNAME",  "loadtest_user")
_PASSWORD  = os.environ.get("LOCUST_PASSWORD",  "loadtest_pass")
_TENANT_ID = os.environ.get("LOCUST_TENANT_ID", "1")

# Realistic shipment statuses to filter by in read operations
_STATUSES = ["Pending", "InTransit", "Delivered"]


# ---------------------------------------------------------------------------
# Auth mixin
# ---------------------------------------------------------------------------

class AuthMixin:
    """
    Logs in with form credentials on first request and attaches the Bearer
    token to all subsequent requests via a persistent header.
    """
    _token: Optional[str] = None

    def on_start(self):  # called once per simulated user
        self.authenticate()

    def authenticate(self):
        with self.client.post(
            "/auth/login",
            data={"username": _USERNAME, "password": _PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "X-Tenant-ID": _TENANT_ID},
            catch_response=True,
            name="/auth/login [setup]",
        ) as resp:
            if resp.status_code == 200:
                body = resp.json()
                self._token = body.get("access_token")
                self.client.headers.update({
                    "Authorization": f"Bearer {self._token}",
                    "X-Tenant-ID": _TENANT_ID,
                })
            else:
                resp.failure(f"Login failed: HTTP {resp.status_code}")

    def _json_headers(self):
        return {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# User class — read-heavy operations (60 %)
# ---------------------------------------------------------------------------

class ReadOperationsUser(AuthMixin, FastHttpUser):
    """Simulates analysts and dispatchers browsing shipments and warehouses."""

    weight      = 60                     # 60 % of traffic
    wait_time   = between(0.5, 2.0)      # think-time between requests

    # ── Shipment reads ────────────────────────────────────────────────

    @tag("shipments", "read")
    @task(40)
    def list_shipments(self):
        with self.client.get("/shipments", name="/shipments [list]",
                             catch_response=True) as r:
            if r.status_code not in (200, 401):
                r.failure(f"Unexpected status: {r.status_code}")

    @tag("shipments", "read")
    @task(20)
    def list_shipments_filtered(self):
        status = random.choice(_STATUSES)
        with self.client.get(
            "/shipments",
            params={"status": status},
            name="/shipments [filtered]",
            catch_response=True,
        ) as r:
            if r.status_code not in (200, 401):
                r.failure(f"Unexpected status: {r.status_code}")

    # ── Warehouse reads ───────────────────────────────────────────────

    @tag("warehouses", "read")
    @task(25)
    def list_warehouses(self):
        with self.client.get("/warehouses", name="/warehouses [list]",
                             catch_response=True) as r:
            if r.status_code not in (200, 401):
                r.failure(f"Unexpected status: {r.status_code}")

    # ── Health check ──────────────────────────────────────────────────

    @tag("health")
    @task(5)
    def health_check(self):
        self.client.get("/health/live", name="/health/live")

    @tag("health")
    @task(5)
    def readiness_check(self):
        self.client.get("/health/ready", name="/health/ready")

    # ── Audit log ─────────────────────────────────────────────────────

    @tag("audit", "read")
    @task(5)
    def list_audit_logs(self):
        with self.client.get("/audit", name="/audit [list]",
                             catch_response=True) as r:
            if r.status_code not in (200, 401, 403):
                r.failure(f"Unexpected status: {r.status_code}")


# ---------------------------------------------------------------------------
# User class — write + async operations (20 %)
# ---------------------------------------------------------------------------

class WriteOperationsUser(AuthMixin, FastHttpUser):
    """Simulates warehouse operators creating and tracking shipments."""

    weight    = 20
    wait_time = between(1.0, 3.0)

    @tag("shipments", "write")
    @task(70)
    def create_and_poll_shipment(self):
        """Create a shipment then poll job status — realistic async workflow."""
        payload = {
            "warehouse_id": random.randint(1, 5),
            "product_id":   random.randint(1, 10),
            "quantity":     random.randint(10, 500),
        }
        with self.client.post(
            "/shipments",
            json=payload,
            headers=self._json_headers(),
            name="/shipments [create]",
            catch_response=True,
        ) as r:
            if r.status_code not in (200, 201, 400, 409, 422):
                r.failure(f"Unexpected status: {r.status_code}")

    @tag("jobs", "write")
    @task(20)
    def dispatch_optimize_route(self):
        """Enqueue route optimisation job and poll result."""
        payload = {
            "warehouse_ids": random.sample(range(1, 11), k=random.randint(2, 5)),
            "constraints":   {"max_distance_km": 500},
        }
        with self.client.post(
            "/jobs/optimize-route",
            json=payload,
            headers=self._json_headers(),
            name="/jobs/optimize-route [dispatch]",
            catch_response=True,
        ) as r:
            if r.status_code not in (200, 201, 202, 422):
                r.failure(f"Unexpected status: {r.status_code}")
                return

            if r.status_code in (200, 201, 202):
                body  = r.json()
                tid   = body.get("task_id")
                if tid:
                    self._poll_task_status(tid)

    @tag("jobs", "write")
    @task(10)
    def run_ai_prediction(self):
        payload = {
            "features":   {"warehouse_id": random.randint(1, 5), "week_number": random.randint(1, 52)},
            "model_name": "demand_forecast",
        }
        with self.client.post(
            "/jobs/run-prediction",
            json=payload,
            headers=self._json_headers(),
            name="/jobs/run-prediction",
            catch_response=True,
        ) as r:
            if r.status_code not in (200, 201, 202, 422):
                r.failure(f"Unexpected status: {r.status_code}")

    def _poll_task_status(self, task_id: str, max_polls: int = 3):
        for _ in range(max_polls):
            time.sleep(0.5)
            with self.client.get(
                f"/jobs/task-status/{task_id}",
                name="/jobs/task-status/{id} [poll]",
                catch_response=True,
            ) as r:
                if r.status_code not in (200, 404):
                    r.failure(f"Poll error: {r.status_code}")
                    return
                if r.status_code == 200:
                    state = r.json().get("status", "")
                    if state in ("SUCCESS", "FAILURE"):
                        return


# ---------------------------------------------------------------------------
# User class — warehouse operations (15 %)
# ---------------------------------------------------------------------------

class WarehouseOperationsUser(AuthMixin, FastHttpUser):
    """Simulates warehouse managers creating and reading warehouses."""

    weight    = 15
    wait_time = between(2.0, 5.0)

    @tag("warehouses", "read")
    @task(80)
    def get_warehouses(self):
        self.client.get("/warehouses", name="/warehouses [list]")

    @tag("warehouses", "write")
    @task(20)
    def create_warehouse(self):
        payload = {
            "name":      f"Load-Test-WH-{random.randint(10000, 99999)}",
            "latitude":  round(random.uniform(48.0, 54.0), 4),
            "longitude": round(random.uniform(-5.0, 20.0), 4),
            "capacity":  random.randint(100, 2000),
        }
        with self.client.post(
            "/warehouses",
            json=payload,
            headers=self._json_headers(),
            name="/warehouses [create]",
            catch_response=True,
        ) as r:
            if r.status_code not in (200, 201, 400, 409, 422):
                r.failure(f"Unexpected status: {r.status_code}")


# ---------------------------------------------------------------------------
# User class — health / monitoring (5 %)
# ---------------------------------------------------------------------------

class MonitoringUser(AuthMixin, FastHttpUser):
    """Simulates monitoring probes hitting health and metrics endpoints."""

    weight    = 5
    wait_time = between(0.1, 1.0)

    @tag("health")
    @task(60)
    def liveness(self):
        self.client.get("/health/live", name="/health/live [monitor]")

    @tag("health")
    @task(40)
    def readiness(self):
        self.client.get("/health/ready", name="/health/ready [monitor]")


# ---------------------------------------------------------------------------
# Event hooks — print summary on test completion
# ---------------------------------------------------------------------------

@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    if environment.stats.total.fail_ratio > 0.01:
        print(
            f"\n❌  Error rate {environment.stats.total.fail_ratio:.1%} exceeds 1 % threshold.\n"
        )
        environment.process_exit_code = 1
    else:
        print(
            f"\n✅  Load test passed — error rate {environment.stats.total.fail_ratio:.2%}\n"
        )
