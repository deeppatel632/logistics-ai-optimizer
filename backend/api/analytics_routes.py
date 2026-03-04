# backend/api/analytics_routes.py
#
# Analytics aggregation endpoints.
# All queries run against the read replica.  Heavy aggregations are cached
# in Redis for 60 seconds to avoid hammering the DB on every dashboard poll.
#
# Routes
# ──────
# GET /analytics/summary     high-level KPI card data (used by Flask dashboard)
# GET /analytics/kpis        delivery-rate, avg throughput, utilisation metrics

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_tenant_id
from backend.core.redis_client import redis_client
from database.connection import get_read_db
from database.models import Inventory, Shipment, Vehicle, Warehouse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

_CACHE_TTL = 60  # seconds


def _get_cached(key: str):
    try:
        raw = redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _set_cached(key: str, value: Any) -> None:
    try:
        redis_client.setex(key, _CACHE_TTL, json.dumps(value))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GET /analytics/summary
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_summary(
    db: Session = Depends(get_read_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> Dict[str, Any]:
    """
    High-level KPI summary consumed by the Flask dashboard and analytics page.

    Returns
    -------
    ```json
    {
      "total_shipments":   120,
      "pending":           30,
      "in_transit":        45,
      "delivered":         40,
      "cancelled":          5,
      "total_warehouses":  8,
      "total_vehicles":    12,
      "available_vehicles": 7,
      "api_status":        "ready"
    }
    ```
    """
    cache_key = f"analytics:summary:{tenant_id}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    # Shipment counts grouped by status
    status_rows = (
        db.query(Shipment.status, func.count(Shipment.id))
        .filter(Shipment.is_deleted.is_(False), Shipment.tenant_id == tenant_id)
        .group_by(Shipment.status)
        .all()
    )
    status_map: Dict[str, int] = {row[0]: row[1] for row in status_rows}
    total = sum(status_map.values())

    # Vehicle counts
    vehicle_rows = (
        db.query(Vehicle.status, func.count(Vehicle.id))
        .filter(Vehicle.is_deleted.is_(False), Vehicle.tenant_id == tenant_id)
        .group_by(Vehicle.status)
        .all()
    )
    vehicle_map: Dict[str, int] = {row[0]: row[1] for row in vehicle_rows}
    total_vehicles = sum(vehicle_map.values())

    # Warehouse count
    total_warehouses = (
        db.query(func.count(Warehouse.id))
        .filter(Warehouse.is_deleted.is_(False), Warehouse.tenant_id == tenant_id)
        .scalar()
    ) or 0

    result: Dict[str, Any] = {
        "total_shipments":    total,
        "pending":            status_map.get("Pending", 0),
        "in_transit":         status_map.get("InTransit", 0),
        "delivered":          status_map.get("Delivered", 0),
        "cancelled":          status_map.get("Cancelled", 0),
        "total_warehouses":   total_warehouses,
        "total_vehicles":     total_vehicles,
        "available_vehicles": vehicle_map.get("Available", 0),
        "api_status":         "ready",
    }

    _set_cached(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# GET /analytics/kpis
# ---------------------------------------------------------------------------

@router.get("/kpis")
def get_kpis(
    db: Session = Depends(get_read_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> Dict[str, Any]:
    """
    Derived KPI metrics for the analytics dashboard charts.

    Returns
    -------
    ```json
    {
      "delivery_rate_pct":   83.3,
      "truck_utilisation_pct": 58.3,
      "warehouse_load": [
        { "warehouse_id": 1, "name": "London Central", "capacity": 1000,
          "stock_quantity": 450, "utilisation_pct": 45.0 }
      ]
    }
    ```
    """
    cache_key = f"analytics:kpis:{tenant_id}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    # Delivery rate
    total: int = db.query(func.count(Shipment.id)).filter(
        Shipment.is_deleted.is_(False), Shipment.tenant_id == tenant_id,
    ).scalar() or 0
    delivered: int = db.query(func.count(Shipment.id)).filter(
        Shipment.is_deleted.is_(False),
        Shipment.tenant_id == tenant_id,
        Shipment.status == "Delivered",
    ).scalar() or 0
    delivery_rate = round((delivered / total * 100), 1) if total > 0 else 0.0

    # Truck utilisation (InTransit / total vehicles)
    total_v: int = db.query(func.count(Vehicle.id)).filter(
        Vehicle.is_deleted.is_(False), Vehicle.tenant_id == tenant_id,
    ).scalar() or 0
    active_v: int = db.query(func.count(Vehicle.id)).filter(
        Vehicle.is_deleted.is_(False),
        Vehicle.tenant_id == tenant_id,
        Vehicle.status == "InTransit",
    ).scalar() or 0
    truck_util = round((active_v / total_v * 100), 1) if total_v > 0 else 0.0

    # Warehouse load — stock vs capacity
    warehouses = (
        db.query(Warehouse)
        .filter(Warehouse.is_deleted.is_(False), Warehouse.tenant_id == tenant_id)
        .all()
    )
    warehouse_load: List[Dict[str, Any]] = []
    for wh in warehouses:
        stock: int = (
            db.query(func.coalesce(func.sum(Inventory.quantity), 0))
            .filter(
                Inventory.warehouse_id == wh.id,
                Inventory.is_deleted.is_(False),
            )
            .scalar()
        ) or 0
        util_pct = round((stock / wh.capacity * 100), 1) if wh.capacity > 0 else 0.0
        warehouse_load.append({
            "warehouse_id":    wh.id,
            "name":            wh.name,
            "capacity":        wh.capacity,
            "stock_quantity":  stock,
            "utilisation_pct": util_pct,
        })

    result = {
        "delivery_rate_pct":     delivery_rate,
        "truck_utilisation_pct": truck_util,
        "warehouse_load":        warehouse_load,
    }

    _set_cached(cache_key, result)
    return result
