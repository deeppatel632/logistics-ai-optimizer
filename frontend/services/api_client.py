# frontend/services/api_client.py
#
# HTTPX-based service layer that wraps every FastAPI endpoint the Flask
# frontend needs.  All methods raise httpx.HTTPStatusError on 4xx/5xx so
# callers can handle errors uniformly.
#
# Usage
# -----
#   from frontend.services.api_client import make_client
#
#   client = make_client(token=session.get("access_token"))
#   summary = client.analytics_summary()
#   ships   = client.list_shipments(status="InTransit")

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class LogisticsAPIClient:
    """Synchronous HTTPX client bound to one JWT token."""

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    # ── Internal helpers ─────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=self._timeout,
        )

    def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        with self._client() as c:
            r = c.get(path, params=params)
            r.raise_for_status()
            return r.json()

    def _post(self, path: str, payload: Dict) -> Any:
        with self._client() as c:
            r = c.post(path, json=payload)
            r.raise_for_status()
            return r.json()

    def _patch(self, path: str, payload: Dict) -> Any:
        with self._client() as c:
            r = c.patch(path, json=payload)
            r.raise_for_status()
            return r.json()

    # ── Auth ─────────────────────────────────────────────────────────

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """
        Authenticate and return ``{"access_token": "...", "token_type": "bearer"}``.
        Uses form encoding as required by the FastAPI OAuth2 endpoint.
        """
        with httpx.Client(base_url=self._base_url, timeout=self._timeout) as c:
            r = c.post(
                "/auth/login",
                data={"username": username, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            return r.json()

    # ── Health ───────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """``GET /health/ready`` — returns ``{"status": "ready"}``."""
        return self._get("/health/ready")

    # ── Analytics ────────────────────────────────────────────────────

    def analytics_summary(self) -> Dict[str, Any]:
        """
        ``GET /analytics/summary``

        Returns tenant-scoped KPI counts::

            {
              "total_shipments": 120,
              "pending": 30,
              "in_transit": 45,
              "delivered": 40,
              "cancelled": 5,
              "total_warehouses": 8,
              "total_vehicles": 12,
              "available_vehicles": 7,
              "api_status": "ready"
            }
        """
        return self._get("/analytics/summary")

    def analytics_kpis(self) -> Dict[str, Any]:
        """
        ``GET /analytics/kpis``

        Returns delivery rate, truck utilisation and per-warehouse load::

            {
              "delivery_rate_pct": 83.3,
              "truck_utilisation_pct": 58.3,
              "warehouse_load": [
                {
                  "warehouse_id": 1,
                  "name": "London Central",
                  "capacity": 1000,
                  "stock_quantity": 450,
                  "utilisation_pct": 45.0
                }
              ]
            }
        """
        return self._get("/analytics/kpis")

    # ── Shipments ────────────────────────────────────────────────────

    def list_shipments(
        self,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """``GET /shipments`` with optional status filter."""
        params: Dict[str, Any] = {"skip": skip, "limit": limit}
        if status:
            params["status"] = status
        result = self._get("/shipments", params=params)
        return result if isinstance(result, list) else []

    def get_shipment(self, shipment_id: int) -> Dict[str, Any]:
        """``GET /shipments/{id}``."""
        return self._get(f"/shipments/{shipment_id}")

    def create_shipment(
        self,
        warehouse_id: int,
        product_id: int,
        quantity: int,
    ) -> Dict[str, Any]:
        """``POST /shipments``."""
        return self._post(
            "/shipments",
            {"warehouse_id": warehouse_id, "product_id": product_id, "quantity": quantity},
        )

    def update_shipment_status(
        self, shipment_id: int, new_status: str
    ) -> Dict[str, Any]:
        """``PUT /shipments/{id}/status``."""
        return self._patch(
            f"/shipments/{shipment_id}/status",
            {"new_status": new_status},
        )

    # ── Vehicles ─────────────────────────────────────────────────────

    def list_vehicles(self) -> List[Dict[str, Any]]:
        """
        ``GET /streaming/vehicles``

        Each vehicle::

            {"id": 1, "type": "Truck", "status": "InTransit",
             "current_latitude": 51.5, "current_longitude": -0.1,
             "tenant_id": 1}
        """
        result = self._get("/streaming/vehicles")
        return result if isinstance(result, list) else []

    def publish_vehicle_location(
        self,
        vehicle_id: int,
        latitude: float,
        longitude: float,
    ) -> Dict[str, Any]:
        """``POST /streaming/vehicle-location``."""
        return self._post(
            "/streaming/vehicle-location",
            {"vehicle_id": vehicle_id, "latitude": latitude, "longitude": longitude},
        )

    # ── Warehouses ───────────────────────────────────────────────────

    def list_warehouses(self) -> List[Dict[str, Any]]:
        """``GET /warehouses``."""
        result = self._get("/warehouses")
        return result if isinstance(result, list) else []

    def create_warehouse(
        self,
        name: str,
        latitude: float,
        longitude: float,
        capacity: int,
    ) -> Dict[str, Any]:
        """``POST /warehouses``."""
        return self._post(
            "/warehouses",
            {
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "capacity": capacity,
            },
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_client(token: Optional[str] = None) -> LogisticsAPIClient:
    """
    Build a :class:`LogisticsAPIClient` wired to the URL and timeout from
    ``frontend.config.settings``.  Import this in Flask route handlers::

        from frontend.services.api_client import make_client

        @app.route("/my-route")
        @login_required
        def my_route():
            client = make_client(token=session.get("access_token"))
            data = client.analytics_summary()
            ...
    """
    from frontend.config import settings
    return LogisticsAPIClient(
        base_url=settings.fastapi_base_url,
        token=token,
        timeout=settings.request_timeout,
    )
