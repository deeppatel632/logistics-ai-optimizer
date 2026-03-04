# simulator/truck_sim.py
#
# Truck telemetry simulation engine.
#
# Behaviour
# ─────────
# 1. Poll FastAPI for shipments in status "InTransit".
# 2. For each shipment that has an assigned vehicle, simulate realistic
#    GPS movement toward a destination warehouse.
# 3. Send a telemetry POST to the FastAPI streaming/location endpoint
#    every TELEMETRY_INTERVAL_S seconds.
# 4. When a simulated truck arrives within ARRIVAL_THRESHOLD_M metres of
#    the destination, mark the shipment as Delivered.
#
# Environment variables
# ─────────────────────
# FASTAPI_BASE_URL      Base URL of the FastAPI service  (default: http://localhost:8000)
# SIM_TOKEN             Bearer JWT for authenticated calls
# TELEMETRY_INTERVAL_S  Seconds between GPS updates       (default: 5)
# SIM_SPEED_KMPH        Simulated truck speed in km/h    (default: 80)
# SIM_LOG_LEVEL         Logging level                    (default: INFO)
#
# Run
# ───
# python -m simulator.truck_sim
# Or: python simulator/truck_sim.py

import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FASTAPI_BASE      = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")
SIM_TOKEN         = os.environ.get("SIM_TOKEN", "")
INTERVAL_S        = float(os.environ.get("TELEMETRY_INTERVAL_S", "5"))
SPEED_KMPH        = float(os.environ.get("SIM_SPEED_KMPH", "80"))
ARRIVAL_M         = float(os.environ.get("ARRIVAL_THRESHOLD_M", "500"))
LOG_LEVEL         = os.environ.get("SIM_LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] truck_sim — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two WGS-84 coordinates."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def step_toward(
    cur_lat: float, cur_lon: float,
    dst_lat: float, dst_lon: float,
    speed_kmph: float,
    interval_s: float,
) -> Tuple[float, float]:
    """Move `speed_kmph` km/h for `interval_s` seconds toward destination.
    Returns new (lat, lon) with ±0.0002° jitter to simulate road noise.
    """
    dist_m = haversine_m(cur_lat, cur_lon, dst_lat, dst_lon)
    if dist_m < 1:
        return dst_lat, dst_lon

    step_m = (speed_kmph * 1000 / 3600) * interval_s
    ratio  = min(step_m / dist_m, 1.0)

    new_lat = cur_lat + ratio * (dst_lat - cur_lat) + random.uniform(-0.0002, 0.0002)
    new_lon = cur_lon + ratio * (dst_lon - cur_lon) + random.uniform(-0.0002, 0.0002)
    return new_lat, new_lon


# ---------------------------------------------------------------------------
# Truck state
# ---------------------------------------------------------------------------

@dataclass
class TruckState:
    vehicle_id:  int
    shipment_id: int
    lat:         float
    lon:         float
    dst_lat:     float
    dst_lon:     float
    delivered:   bool = False
    steps:       int  = 0


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def _headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if SIM_TOKEN:
        h["Authorization"] = f"Bearer {SIM_TOKEN}"
    return h


def _client() -> httpx.Client:
    return httpx.Client(base_url=FASTAPI_BASE, headers=_headers(), timeout=8.0)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fetch_active_shipments() -> List[dict]:
    """Return shipments with status InTransit that have a vehicle."""
    try:
        with _client() as c:
            r = c.get("/shipments", params={"status": "InTransit"})
            r.raise_for_status()
            data = r.json()
            return [s for s in (data if isinstance(data, list) else []) if s.get("vehicle_id")]
    except Exception as exc:
        logger.warning("fetch_shipments error: %s", exc)
        return []


def fetch_warehouse(warehouse_id: int) -> Optional[dict]:
    """Return warehouse record (has latitude/longitude)."""
    try:
        with _client() as c:
            r = c.get(f"/warehouses/{warehouse_id}")
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("fetch_warehouse(%d) error: %s", warehouse_id, exc)
        return None


def post_location(vehicle_id: int, lat: float, lon: float) -> bool:
    """POST GPS telemetry to /streaming/location."""
    try:
        with _client() as c:
            r = c.post("/streaming/location", json={
                "vehicle_id": vehicle_id,
                "latitude":   lat,
                "longitude":  lon,
            })
            r.raise_for_status()
            return True
    except httpx.HTTPStatusError as exc:
        logger.error("post_location %d: HTTP %d", vehicle_id, exc.response.status_code)
    except Exception as exc:
        logger.error("post_location %d: %s", vehicle_id, exc)
    return False


def mark_delivered(shipment_id: int) -> None:
    """PATCH shipment status to Delivered."""
    try:
        with _client() as c:
            r = c.patch(f"/shipments/{shipment_id}", json={"status": "Delivered"})
            r.raise_for_status()
            logger.info("shipment #%d marked Delivered", shipment_id)
    except Exception as exc:
        logger.warning("mark_delivered(%d) error: %s", shipment_id, exc)


# ---------------------------------------------------------------------------
# Simulator loop
# ---------------------------------------------------------------------------

def build_truck_states(shipments: List[dict]) -> Dict[int, TruckState]:
    """Initialise a TruckState for each active shipment."""
    states: Dict[int, TruckState] = {}
    for s in shipments:
        vid = s["vehicle_id"]
        if vid in states:
            continue  # one simulation per vehicle

        # Fetch destination warehouse coordinates
        wh = fetch_warehouse(s["warehouse_id"])
        if not wh:
            continue

        # Start position: small random offset from the warehouse
        start_lat = wh["latitude"]  + random.uniform(-1.5, 1.5)
        start_lon = wh["longitude"] + random.uniform(-1.5, 1.5)

        states[vid] = TruckState(
            vehicle_id  = vid,
            shipment_id = s["id"],
            lat         = start_lat,
            lon         = start_lon,
            dst_lat     = wh["latitude"],
            dst_lon     = wh["longitude"],
        )
        logger.info(
            "truck #%d → shipment #%d | start (%.4f, %.4f) → dst (%.4f, %.4f)",
            vid, s["id"], start_lat, start_lon, wh["latitude"], wh["longitude"],
        )

    return states


def run_simulation() -> None:
    logger.info("=== Truck Telemetry Simulator starting ===")
    logger.info("backend=%s  interval=%.1fs  speed=%.0f km/h",
                FASTAPI_BASE, INTERVAL_S, SPEED_KMPH)

    trucks: Dict[int, TruckState] = {}

    while True:
        # Reload active shipments every 30 s (or on first run)
        if not trucks:
            shipments = fetch_active_shipments()
            if not shipments:
                logger.info("no active shipments — waiting 30 s …")
                time.sleep(30)
                continue
            trucks = build_truck_states(shipments)

        for vid, t in list(trucks.items()):
            if t.delivered:
                continue

            # Move truck one step
            t.lat, t.lon = step_toward(
                t.lat, t.lon, t.dst_lat, t.dst_lon, SPEED_KMPH, INTERVAL_S
            )
            t.steps += 1

            # Send telemetry
            ok = post_location(vid, t.lat, t.lon)
            logger.debug(
                "truck #%d step=%d (%.4f, %.4f) published=%s",
                vid, t.steps, t.lat, t.lon, ok,
            )

            # Check arrival
            dist = haversine_m(t.lat, t.lon, t.dst_lat, t.dst_lon)
            if dist <= ARRIVAL_M:
                logger.info("truck #%d ARRIVED — shipment #%d", vid, t.shipment_id)
                mark_delivered(t.shipment_id)
                t.delivered = True

        # Drop delivered trucks; refresh next cycle
        trucks = {v: t for v, t in trucks.items() if not t.delivered}

        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    try:
        run_simulation()
    except KeyboardInterrupt:
        logger.info("simulator stopped by user")
