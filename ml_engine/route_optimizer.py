# ml_engine/route_optimizer.py
#
# AI Route Optimization Engine
#
# Algorithms
# ──────────
# 1. nearest_vehicle()      — select the geographically nearest Available vehicle
#                             to a target warehouse using Haversine distance.
# 2. optimize_dispatch()    — greedy nearest-neighbour TSP over a list of
#                             warehouse coordinates; returns the visit order
#                             that minimises total travel distance.
# 3. predict_eta()          — estimate ETA using speed ÷ distance; optionally
#                             uses a trained scikit-learn model when one is
#                             found on disk.
# 4. RouteOptimizer.run()   — end-to-end pipeline: selects vehicle → builds
#                             optimised route → predicts ETA per stop.
#
# Integration
# ───────────
# Called from backend/workers/tasks.py::optimize_routes() Celery task.
# Can also be used standalone:
#
#   from ml_engine.route_optimizer import RouteOptimizer
#   result = RouteOptimizer().run(warehouse_ids=[1, 4, 7], vehicles=vehicles)

import logging
import math
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M  = 6_371_000.0
_DEFAULT_SPEED   = 80.0          # km/h — used when no model is available
_MODEL_PATH      = Path(__file__).parent / "models" / "eta_model.pkl"


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in kilometres."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 2 * (_EARTH_RADIUS_M / 1000) * math.asin(math.sqrt(a))


def _distance_matrix(coords: List[Tuple[float, float]]) -> np.ndarray:
    """Compute a symmetric NxN Haversine distance matrix (km)."""
    n = len(coords)
    dm = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
            dm[i, j] = dm[j, i] = d
    return dm


# ---------------------------------------------------------------------------
# Vehicle selection
# ---------------------------------------------------------------------------

def nearest_vehicle(
    target_lat: float,
    target_lon: float,
    vehicles: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Return the Available vehicle closest to (target_lat, target_lon).

    Parameters
    ----------
    target_lat, target_lon:
        Destination coordinates (e.g. first warehouse on the route).
    vehicles:
        List of vehicle dicts with keys: id, status, current_latitude,
        current_longitude.  Only vehicles with status == "Available" are
        considered.

    Returns None when no available vehicle exists.
    """
    available = [v for v in vehicles if v.get("status") == "Available"]
    if not available:
        logger.warning("nearest_vehicle: no available vehicles")
        return None

    best: Optional[Dict[str, Any]] = None
    best_dist = float("inf")

    for v in available:
        lat = v.get("current_latitude")
        lon = v.get("current_longitude")
        if lat is None or lon is None:
            continue
        d = haversine_km(target_lat, target_lon, lat, lon)
        if d < best_dist:
            best_dist = d
            best = v

    if best:
        logger.info(
            "nearest_vehicle: selected vehicle #%d (%.2f km away)",
            best["id"], best_dist,
        )
    return best


# ---------------------------------------------------------------------------
# Route optimisation  (greedy nearest-neighbour TSP)
# ---------------------------------------------------------------------------

def optimize_dispatch(
    warehouses: List[Dict[str, Any]],
    start_lat: Optional[float] = None,
    start_lon: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Greedy nearest-neighbour TSP on a list of warehouses.

    Parameters
    ----------
    warehouses:
        List of warehouse dicts with keys: id, latitude, longitude (+ any
        extra keys which are passed through unchanged).
    start_lat, start_lon:
        Optional departure coordinates (e.g. vehicle's current position).
        If omitted, the first warehouse in the list is used as the start.

    Returns
    -------
    Ordered list of warehouses representing the optimised visit sequence,
    annotated with an extra key ``leg_distance_km`` for each stop.
    """
    if not warehouses:
        return []

    coords: List[Tuple[float, float]] = [
        (w["latitude"], w["longitude"]) for w in warehouses
    ]
    dm = _distance_matrix(coords)
    n  = len(warehouses)

    if start_lat is not None and start_lon is not None:
        # Prepend a virtual "depot" node
        depot_dists = np.array([
            haversine_km(start_lat, start_lon, lat, lon) for lat, lon in coords
        ])
        current = -1  # virtual depot index
        unvisited = list(range(n))
    else:
        # Start from the first warehouse
        current   = 0
        unvisited = list(range(1, n))

    route_indices: List[int] = [] if current == -1 else [0]

    while unvisited:
        if current == -1:
            distances = depot_dists[unvisited]
        else:
            distances = dm[current][unvisited]

        nearest_idx = int(np.argmin(distances))
        next_wh     = unvisited[nearest_idx]
        route_indices.append(next_wh)
        current = next_wh
        unvisited.pop(nearest_idx)

    # Annotate with per-leg distances
    result = []
    for i, idx in enumerate(route_indices):
        wh = dict(warehouses[idx])
        if i == 0:
            if start_lat is not None:
                wh["leg_distance_km"] = round(
                    haversine_km(start_lat, start_lon, wh["latitude"], wh["longitude"]), 2
                )
            else:
                wh["leg_distance_km"] = 0.0
        else:
            prev = warehouses[route_indices[i - 1]]
            wh["leg_distance_km"] = round(
                haversine_km(prev["latitude"], prev["longitude"],
                             wh["latitude"], wh["longitude"]), 2
            )
        result.append(wh)

    total_km = sum(w["leg_distance_km"] for w in result)
    logger.info("optimize_dispatch: %d stops, total %.2f km", n, total_km)
    return result


# ---------------------------------------------------------------------------
# ETA prediction
# ---------------------------------------------------------------------------

def _load_eta_model() -> Optional[Any]:
    if _MODEL_PATH.exists():
        try:
            with open(_MODEL_PATH, "rb") as fh:
                model = pickle.load(fh)
            logger.info("eta_model loaded from %s", _MODEL_PATH)
            return model
        except Exception as exc:
            logger.warning("eta_model load failed: %s — falling back to heuristic", exc)
    return None


_ETA_MODEL = _load_eta_model()


def predict_eta(
    distance_km: float,
    hour_of_day:  int = 12,
    day_of_week:  int = 1,
    speed_kmph:   float = _DEFAULT_SPEED,
) -> float:
    """
    Predict ETA in hours for a given distance.

    Uses a trained scikit-learn model (``ml_engine/models/eta_model.pkl``)
    when available; otherwise falls back to distance ÷ speed with a traffic
    multiplier based on the hour of day.

    Parameters
    ----------
    distance_km:  Total route distance.
    hour_of_day:  0-23 — used by the traffic heuristic.
    day_of_week:  0=Mon … 6=Sun — used by the traffic heuristic.
    speed_kmph:   Fallback speed when no model is loaded.

    Returns
    -------
    Estimated travel time in hours (float).
    """
    if _ETA_MODEL is not None:
        try:
            features = np.array([[distance_km, hour_of_day, day_of_week]])
            eta: float = float(_ETA_MODEL.predict(features)[0])
            return round(max(eta, 0.1), 2)
        except Exception as exc:
            logger.warning("eta_model.predict failed: %s — using heuristic", exc)

    # Heuristic: adjust speed for peak hours
    if 7 <= hour_of_day <= 9 or 17 <= hour_of_day <= 19:
        effective_speed = speed_kmph * 0.65   # heavy traffic
    elif 22 <= hour_of_day or hour_of_day <= 5:
        effective_speed = speed_kmph * 1.10   # light traffic
    else:
        effective_speed = speed_kmph

    return round(distance_km / effective_speed, 2)


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------

@dataclass
class OptimisationResult:
    vehicle_id:      Optional[int]
    optimised_route: List[Dict[str, Any]]
    total_distance_km: float
    estimated_eta_hours: float
    algorithm:       str = "greedy_nearest_neighbour"
    warnings:        List[str] = field(default_factory=list)


class RouteOptimizer:
    """
    High-level optimizer that wires together vehicle selection, route
    optimisation and ETA prediction.

    Usage
    ─────
    from ml_engine.route_optimizer import RouteOptimizer

    result = RouteOptimizer().run(
        warehouse_ids=[1, 4, 7],
        warehouses=list_of_warehouse_dicts,
        vehicles=list_of_vehicle_dicts,
    )
    """

    def run(
        self,
        warehouses: List[Dict[str, Any]],
        vehicles:   List[Dict[str, Any]],
        hour_of_day: int = 12,
        day_of_week: int = 1,
    ) -> OptimisationResult:
        """
        Run the full optimisation pipeline.

        Parameters
        ----------
        warehouses:
            Unordered list of warehouse dictionaries (id, latitude, longitude).
        vehicles:
            List of vehicle dictionaries (id, status, current_latitude,
            current_longitude).
        hour_of_day, day_of_week:
            Calendar context for ETA prediction.

        Returns
        -------
        OptimisationResult dataclass.
        """
        warnings: List[str] = []

        if not warehouses:
            return OptimisationResult(
                vehicle_id=None,
                optimised_route=[],
                total_distance_km=0.0,
                estimated_eta_hours=0.0,
                warnings=["No warehouses provided"],
            )

        # 1. Select nearest vehicle to the first warehouse
        first = warehouses[0]
        vehicle = nearest_vehicle(first["latitude"], first["longitude"], vehicles)

        start_lat = vehicle["current_latitude"]  if vehicle else None
        start_lon = vehicle["current_longitude"] if vehicle else None

        if vehicle is None:
            warnings.append("No available vehicle found — route computed without vehicle assignment")

        # 2. Optimise dispatch order
        route = optimize_dispatch(warehouses, start_lat=start_lat, start_lon=start_lon)

        # 3. Totals
        total_km = sum(w.get("leg_distance_km", 0.0) for w in route)
        if vehicle and start_lat is not None:
            # Add distance from vehicle to first stop
            vehicle_to_first = haversine_km(
                start_lat, start_lon, route[0]["latitude"], route[0]["longitude"]
            )
            total_km += vehicle_to_first

        # 4. ETA prediction
        eta_hours = predict_eta(total_km, hour_of_day=hour_of_day, day_of_week=day_of_week)

        return OptimisationResult(
            vehicle_id=vehicle["id"] if vehicle else None,
            optimised_route=route,
            total_distance_km=round(total_km, 2),
            estimated_eta_hours=eta_hours,
            warnings=warnings,
        )
