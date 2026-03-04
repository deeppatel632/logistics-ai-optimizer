# simulator/truck_sim.py
#
# Multi-threaded truck telemetry simulation engine.
#
# Behaviour
# ─────────
# 1. Poll FastAPI GET /shipments?status=InTransit for active shipments.
# 2. For each shipment that has an assigned vehicle and is not already
#    being simulated, spawn a dedicated daemon thread.
# 3. Each thread:
#    a. Fetches the destination warehouse coordinates.
#    b. Pre-computes a GPS route via generate_route_points().
#    c. Walks the route, sending a telemetry POST to
#       POST /streaming/vehicle-location every INTERVAL_S seconds.
#    d. On arrival (within ARRIVAL_M metres) sends a final telemetry
#       update then marks the shipment delivered via
#       PUT /shipments/{id}/status?new_status=Delivered.
# 4. The main thread re-polls every POLL_INTERVAL_S and spawns threads
#    for any newly discovered shipments.
#
# Environment variables
# ─────────────────────
# FASTAPI_BASE_URL      FastAPI base URL              (default: http://localhost:8000)
# SIM_TOKEN             Bearer JWT for auth calls     (default: empty / dev bypass)
# TELEMETRY_INTERVAL_S  Seconds between GPS updates   (default: 5)
# SIM_SPEED_KMPH        Truck speed in km/h           (default: 60)
#                        Jittered ±10 km/h per truck for realism)
# ARRIVAL_THRESHOLD_M   Arrival radius in metres      (default: 500)
# ROUTE_WAYPOINTS       Number of pre-computed waypoints per route (default: 120)
# POLL_INTERVAL_S       How often to re-poll for new shipments (default: 30)
# SIM_LOG_LEVEL         Python log level              (default: INFO)
#
# Run
# ───
#   python -m simulator.truck_sim       # recommended (package imports)
#   python simulator/truck_sim.py       # direct run from project root

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import httpx

from simulator.utils import (
    bearing_degrees,
    generate_route_points,
    haversine_m,
    now_iso,
    simulate_movement,
    step_toward,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FASTAPI_BASE    = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")
SIM_TOKEN       = os.environ.get("SIM_TOKEN", "")
INTERVAL_S      = float(os.environ.get("TELEMETRY_INTERVAL_S", "5"))
SPEED_KMPH      = float(os.environ.get("SIM_SPEED_KMPH", "60"))
ARRIVAL_M       = float(os.environ.get("ARRIVAL_THRESHOLD_M", "500"))
WAYPOINTS       = int(os.environ.get("ROUTE_WAYPOINTS", "120"))
POLL_INTERVAL_S = float(os.environ.get("POLL_INTERVAL_S", "30"))
LOG_LEVEL       = os.environ.get("SIM_LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("truck_sim")

# Tracks which vehicle IDs already have a live thread
_active_vehicles: Set[int] = set()
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers() -> Dict[str, str]:
    h: Dict[str, str] = {"Content-Type": "application/json"}
    if SIM_TOKEN:
        h["Authorization"] = f"Bearer {SIM_TOKEN}"
    return h


def _client() -> httpx.Client:
    return httpx.Client(base_url=FASTAPI_BASE, headers=_headers(), timeout=8.0)


# ---------------------------------------------------------------------------
# FastAPI calls
# ---------------------------------------------------------------------------

def fetch_active_shipments() -> List[dict]:
    """GET /shipments?status=InTransit — return shipments that have a vehicle."""
    try:
        with _client() as c:
            r = c.get("/shipments", params={"status": "InTransit", "limit": 500})
            r.raise_for_status()
            data = r.json()
            shipments = data if isinstance(data, list) else []
            return [s for s in shipments if s.get("vehicle_id")]
    except Exception as exc:
        logger.warning("fetch_active_shipments error: %s", exc)
        return []


def fetch_warehouse(warehouse_id: int) -> Optional[dict]:
    """GET /warehouses/{id} — returns {id, name, latitude, longitude, capacity}."""
    try:
        with _client() as c:
            r = c.get(f"/warehouses/{warehouse_id}")
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("fetch_warehouse(%d) error: %s", warehouse_id, exc)
        return None


def post_vehicle_location(
    vehicle_id: int,
    lat: float,
    lon: float,
    speed_kmh: float,
    heading: float,
) -> bool:
    """POST /streaming/vehicle-location — publish a GPS fix to Kafka.

    Payload matches ``VehicleLocationEvent`` schema exactly:

    .. code-block:: json

        {
            "vehicle_id":       "42",
            "latitude":         51.5050,
            "longitude":        -0.0900,
            "timestamp":        "2026-03-04T10:15:30Z",
            "speed_kmh":        58.3,
            "heading_degrees":  274.1
        }

    ``vehicle_id`` is sent as a **string** to match the backend schema.
    """
    try:
        with _client() as c:
            r = c.post(
                "/streaming/vehicle-location",
                json={
                    "vehicle_id":       str(vehicle_id),
                    "latitude":         round(lat, 6),
                    "longitude":        round(lon, 6),
                    "timestamp":        now_iso(),
                    "speed_kmh":        round(speed_kmh, 1),
                    "heading_degrees":  round(heading, 1),
                },
            )
            r.raise_for_status()
            return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "post_vehicle_location vehicle=%d http=%d body=%s",
            vehicle_id, exc.response.status_code, exc.response.text[:200],
        )
    except Exception as exc:
        logger.error("post_vehicle_location vehicle=%d error: %s", vehicle_id, exc)
    return False


def mark_shipment_delivered(shipment_id: int) -> None:
    """PUT /shipments/{id}/status?new_status=Delivered

    Uses the change_status route which requires ``new_status`` as a query
    parameter and a valid Bearer token in ``Authorization``.
    """
    try:
        with _client() as c:
            r = c.put(
                f"/shipments/{shipment_id}/status",
                params={"new_status": "Delivered"},
            )
            r.raise_for_status()
            logger.info("shipment #%d → Delivered ✓", shipment_id)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "mark_delivered shipment=%d http=%d — %s",
            shipment_id, exc.response.status_code, exc.response.text[:200],
        )
    except Exception as exc:
        logger.warning("mark_delivered shipment=%d error: %s", shipment_id, exc)


# ---------------------------------------------------------------------------
# Per-truck thread
# ---------------------------------------------------------------------------

@dataclass
class TruckState:
    """All mutable state owned by a single truck thread."""

    vehicle_id:  int
    shipment_id: int
    # Current position
    lat: float
    lon: float
    # Destination warehouse position
    dst_lat: float
    dst_lon: float
    dst_name: str = ""
    # Per-truck speed variation: ±10 km/h around the global default
    speed_kmph: float = field(default_factory=lambda: SPEED_KMPH + random.uniform(-10, 10))
    steps: int = 0


def _run_truck(state: TruckState) -> None:
    """Target function for each truck thread.

    1. Pre-computes a curved route from start → destination warehouse.
    2. Iterates through waypoints, sending telemetry at each step.
    3. Falls back to step_toward() if remaining distance is not covered
       by the pre-computed waypoints (e.g., the truck overshoots).
    4. Marks shipment delivered on arrival.
    """
    tlog = logging.getLogger(f"truck_sim.truck_{state.vehicle_id}")

    tlog.info(
        "STARTED  vehicle=#%d  shipment=#%d  start=(%.4f, %.4f)  dst=%s (%.4f, %.4f)",
        state.vehicle_id, state.shipment_id,
        state.lat, state.lon,
        state.dst_name, state.dst_lat, state.dst_lon,
    )

    # Pre-compute waypoints
    route = generate_route_points(
        start=(state.lat, state.lon),
        end=(state.dst_lat, state.dst_lon),
        steps=WAYPOINTS,
    )

    prev_lat, prev_lon = state.lat, state.lon

    for lat, lon in simulate_movement(route):
        state.lat, state.lon = lat, lon
        state.steps += 1

        heading = bearing_degrees(prev_lat, prev_lon, lat, lon)
        dist_m  = haversine_m(lat, lon, state.dst_lat, state.dst_lon)

        ok = post_vehicle_location(
            state.vehicle_id, lat, lon, state.speed_kmph, heading
        )

        tlog.info(
            "step=%d  pos=(%.4f, %.4f)  remaining=%.0f m  heading=%.0f°  published=%s",
            state.steps, lat, lon, dist_m, heading, ok,
        )

        prev_lat, prev_lon = lat, lon

        # Arrived?
        if dist_m <= ARRIVAL_M:
            break

        time.sleep(INTERVAL_S)

    # Final position — send one last update exactly on the destination
    post_vehicle_location(
        state.vehicle_id,
        state.dst_lat, state.dst_lon,
        0.0,   # stopped
        0.0,
    )

    tlog.info(
        "ARRIVED  vehicle=#%d  shipment=#%d  total_steps=%d",
        state.vehicle_id, state.shipment_id, state.steps,
    )

    mark_shipment_delivered(state.shipment_id)

    with _lock:
        _active_vehicles.discard(state.vehicle_id)


# ---------------------------------------------------------------------------
# Main orchestration loop
# ---------------------------------------------------------------------------

def _spawn_truck(shipment: dict) -> None:
    """Fetch warehouse coords and start a truck thread for this shipment."""
    vid  = shipment["vehicle_id"]
    sid  = shipment["id"]
    whid = shipment["warehouse_id"]

    wh = fetch_warehouse(whid)
    if not wh:
        logger.warning("cannot fetch warehouse %d for shipment %d — skipping", whid, sid)
        return

    dst_lat = wh["latitude"]
    dst_lon = wh["longitude"]

    # Randomised start position within ~150 km of the destination warehouse
    start_lat = dst_lat + random.uniform(-1.5, 1.5)
    start_lon = dst_lon + random.uniform(-1.5, 1.5)

    state = TruckState(
        vehicle_id  = vid,
        shipment_id = sid,
        lat         = start_lat,
        lon         = start_lon,
        dst_lat     = dst_lat,
        dst_lon     = dst_lon,
        dst_name    = wh.get("name", str(whid)),
    )

    t = threading.Thread(
        target=_run_truck,
        args=(state,),
        name=f"truck-{vid}",
        daemon=True,         # won't block process exit
    )
    t.start()
    logger.info("spawned thread for vehicle #%d (shipment #%d)", vid, sid)


def run_simulation() -> None:
    """Entry-point: poll for active shipments and manage truck threads.

    Runs until interrupted with Ctrl-C.  Each call to ``run_simulation()``
    is purely synchronous — threading happens inside ``_spawn_truck()``.
    """
    logger.info("=" * 60)
    logger.info("  Logistics AI — Truck Telemetry Simulator")
    logger.info("  backend      : %s", FASTAPI_BASE)
    logger.info("  interval     : %.1f s", INTERVAL_S)
    logger.info("  speed        : %.0f km/h (±10 jitter per truck)", SPEED_KMPH)
    logger.info("  waypoints    : %d per route", WAYPOINTS)
    logger.info("  arrival zone : %.0f m", ARRIVAL_M)
    logger.info("  poll every   : %.0f s", POLL_INTERVAL_S)
    logger.info("=" * 60)

    while True:
        shipments = fetch_active_shipments()

        if not shipments:
            logger.info("no active InTransit shipments — will retry in %.0f s …", POLL_INTERVAL_S)
        else:
            logger.info("found %d active shipment(s)", len(shipments))

            for s in shipments:
                vid = s["vehicle_id"]
                with _lock:
                    already_running = vid in _active_vehicles

                if already_running:
                    logger.debug("vehicle #%d already simulating — skipping", vid)
                    continue

                with _lock:
                    _active_vehicles.add(vid)

                _spawn_truck(s)

        time.sleep(POLL_INTERVAL_S)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        run_simulation()
    except KeyboardInterrupt:
        logger.info("simulator stopped by user (KeyboardInterrupt)")
    except Exception as exc:
        logger.exception("simulator crashed: %s", exc)
        raise
