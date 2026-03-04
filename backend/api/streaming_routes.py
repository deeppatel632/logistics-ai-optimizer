# backend/api/streaming_routes.py
#
# ---------------------------------------------------------------------------
# Real-time event streaming endpoints
# ---------------------------------------------------------------------------
#
# This router publishes inbound HTTP payloads as Kafka events.  The API
# returns immediately after publish; downstream Kafka consumers process the
# event asynchronously (route engine, analytics service, ML prediction).
#
# Topics used:
#   vehicle-location-topic    — GPS position updates from vehicles / IoT devices
#   delivery-status-topic     — delivery lifecycle events (picked up, in transit,
#                               delivered, failed)
#   inventory-update-topic    — warehouse stock-level changes
#   iot-sensor-topic          — raw IoT sensor readings
#   route-optimization-topic  — triggers a route recalculation for a vehicle
#   ai-prediction-topic       — triggers an AI demand / ETA prediction job
#
# ---------------------------------------------------------------------------

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.core.dependencies import get_current_tenant_id
from backend.streaming.kafka_producer import publish_event
from database.connection import get_read_db
from database.models import Vehicle
from kafka.errors import KafkaError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streaming", tags=["Streaming"])


# ---------------------------------------------------------------------------
# GET /streaming/vehicles  — realtime vehicle list for the tracking map
# ---------------------------------------------------------------------------

@router.get("/vehicles", summary="List all active vehicles with current GPS position")
def list_vehicles(
    db: Session = Depends(get_read_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    """Return all non-deleted vehicles for the current tenant.  The Flask
    dashboard vehicle-tracking map polls this endpoint every 5 seconds."""
    vehicles = (
        db.query(Vehicle)
        .filter(Vehicle.tenant_id == tenant_id, Vehicle.is_deleted.is_(False))
        .all()
    )
    return [
        {
            "id":                v.id,
            "type":              v.type,
            "status":            v.status,
            "current_latitude":  v.current_latitude,
            "current_longitude": v.current_longitude,
            "tenant_id":         v.tenant_id,
        }
        for v in vehicles
    ]


# ---------------------------------------------------------------------------
# Event schemas
# ---------------------------------------------------------------------------

class VehicleLocationEvent(BaseModel):
    """GPS location update published by a vehicle or IoT device.

    Example event that consumers receive on ``vehicle-location-topic``::

        {
            "vehicle_id": "TRUCK_102",
            "latitude": 23.0225,
            "longitude": 72.5714,
            "timestamp": "2026-03-04T10:30:00Z"
        }
    """

    vehicle_id: str = Field(
        ...,
        description="Unique vehicle identifier",
        examples=["TRUCK_102"],
    )
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude in decimal degrees (WGS-84)",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude in decimal degrees (WGS-84)",
    )
    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp of the location reading",
        examples=["2026-03-04T10:30:00Z"],
    )
    speed_kmh: float | None = Field(
        default=None,
        ge=0,
        description="Optional: current speed in km/h",
    )
    heading_degrees: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="Optional: bearing in degrees (0 = North, clockwise)",
    )


class DeliveryStatusEvent(BaseModel):
    """Delivery lifecycle event."""

    shipment_id: str = Field(..., examples=["SHIP_20260304_001"])
    vehicle_id: str = Field(..., examples=["TRUCK_102"])
    status: str = Field(
        ...,
        description="One of: picked_up | in_transit | delivered | failed",
        examples=["in_transit"],
    )
    timestamp: str = Field(..., examples=["2026-03-04T11:00:00Z"])
    location_lat: float | None = None
    location_lng: float | None = None
    notes: str | None = None


class WarehouseInventoryEvent(BaseModel):
    """Stock-level change event."""

    warehouse_id: int
    sku: str = Field(..., examples=["SKU-98765"])
    quantity_delta: int = Field(
        ...,
        description="Change in stock quantity (positive = stock in, negative = stock out)",
    )
    timestamp: str = Field(..., examples=["2026-03-04T09:00:00Z"])


class IoTSensorEvent(BaseModel):
    """Raw IoT sensor reading."""

    sensor_id: str
    sensor_type: str = Field(
        ...,
        examples=["temperature", "humidity", "door_open"],
    )
    value: Any
    unit: str | None = None
    timestamp: str


class RouteOptimizationTrigger(BaseModel):
    """Trigger a route recalculation for a vehicle."""

    vehicle_id: str
    reason: str = Field(
        ...,
        examples=["traffic_jam", "new_stop_added", "vehicle_breakdown"],
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class AIPredictionTrigger(BaseModel):
    """Trigger an AI demand or ETA prediction job."""

    prediction_type: str = Field(
        ...,
        examples=["demand_forecast", "eta_prediction", "anomaly_detection"],
    )
    scope: dict[str, Any] = Field(
        ...,
        description="Prediction scope parameters (e.g. warehouse_id, route_id)",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _publish(topic: str, data: dict, key: str | None = None) -> dict:
    """Publish to Kafka and return a uniform confirmation response."""
    try:
        publish_event(topic, data, key=key)
        return {"status": "event published", "topic": topic}
    except KafkaError as exc:
        logger.exception("kafka_publish_route_error", extra={"topic": topic})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Kafka unavailable: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/vehicle-location",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish a vehicle GPS location event",
    response_description="Event published to Kafka",
)
def post_vehicle_location(event: VehicleLocationEvent) -> dict:
    """Receive a vehicle GPS update and publish it to ``vehicle-location-topic``.

    Downstream consumers (route engine, ETA predictor) react to this event
    asynchronously.  Using ``vehicle_id`` as the Kafka partition key ensures
    that all location events for a single vehicle land on the same partition,
    preserving per-vehicle ordering.

    **Example request body:**
    ```json
    {
        "vehicle_id": "TRUCK_102",
        "latitude": 23.0225,
        "longitude": 72.5714,
        "timestamp": "2026-03-04T10:30:00Z"
    }
    ```
    """
    return _publish(
        topic="vehicle-location-topic",
        data=event.model_dump(),
        key=event.vehicle_id,  # same vehicle → same partition → ordering preserved
    )


@router.post(
    "/delivery-status",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish a delivery status change event",
)
def post_delivery_status(event: DeliveryStatusEvent) -> dict:
    """Publish a delivery lifecycle change to ``delivery-status-topic``."""
    return _publish(
        topic="delivery-status-topic",
        data=event.model_dump(),
        key=event.shipment_id,
    )


@router.post(
    "/inventory-update",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish a warehouse inventory change event",
)
def post_inventory_update(event: WarehouseInventoryEvent) -> dict:
    """Publish a stock-level change to ``inventory-update-topic``."""
    return _publish(
        topic="inventory-update-topic",
        data=event.model_dump(),
        key=str(event.warehouse_id),
    )


@router.post(
    "/iot-sensor",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Publish a raw IoT sensor reading",
)
def post_iot_sensor(event: IoTSensorEvent) -> dict:
    """Publish a sensor reading to ``iot-sensor-topic``."""
    return _publish(
        topic="iot-sensor-topic",
        data=event.model_dump(),
        key=event.sensor_id,
    )


@router.post(
    "/trigger-route-optimization",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a route re-optimisation for a vehicle",
)
def trigger_route_optimization(trigger: RouteOptimizationTrigger) -> dict:
    """Publish a route optimisation trigger to ``route-optimization-topic``.

    The route engine consumer picks this up and dispatches a Celery optimise_routes task.
    """
    return _publish(
        topic="route-optimization-topic",
        data=trigger.model_dump(),
        key=trigger.vehicle_id,
    )


@router.post(
    "/trigger-ai-prediction",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger an AI prediction job",
)
def trigger_ai_prediction(trigger: AIPredictionTrigger) -> dict:
    """Publish an AI prediction trigger to ``ai-prediction-topic``.

    The ML service consumer picks this up and dispatches a Celery run_ai_prediction task.
    """
    return _publish(
        topic="ai-prediction-topic",
        data=trigger.model_dump(),
    )
