# ml_engine/utils.py
#
# Pure utility functions shared by every module in ml_engine/.
# No I/O side-effects except load_model / save_model.
#
# Public API
# ──────────
# haversine_distance(lat1, lon1, lat2, lon2) → float   great-circle km
# traffic_factor(hour)                        → float   0-1 congestion multiplier
# vehicle_speed_kmph(vehicle_type)            → float   nominal speed from type
# vehicle_capacity_kg(vehicle_type)           → float   payload kg from type
# build_feature_vector(vehicle, shipment)     → np.ndarray  (1, 6) feature matrix
# generate_synthetic_training_data(n, seed)   → pd.DataFrame
# load_model(path)                            → model | None
# save_model(model, path)                     → None

from __future__ import annotations

import logging
import math
import pickle
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EARTH_R_KM = 6_371.0

# Vehicle type → nominal cruise speed (km/h)
VEHICLE_SPEEDS: Dict[str, float] = {
    "Truck":        80.0,
    "Semi":         75.0,
    "Van":          100.0,
    "Refrigerated": 70.0,
    "Bike":         35.0,
}
_DEFAULT_SPEED = 80.0

# Vehicle type → max payload (kg)
VEHICLE_CAPACITIES: Dict[str, float] = {
    "Truck":        10_000.0,
    "Semi":         25_000.0,
    "Van":           2_000.0,
    "Refrigerated":  8_000.0,
    "Bike":            100.0,
}
_DEFAULT_CAPACITY = 5_000.0

# Column order for every feature vector — MUST match eta_model training
FEATURE_COLUMNS = [
    "distance_vehicle_to_source",   # km  — vehicle current pos → warehouse
    "distance_source_to_dest",      # km  — warehouse → delivery destination
    "vehicle_capacity_kg",          # kg
    "vehicle_speed_kmph",           # km/h
    "traffic_factor",               # 0.0–1.0 (1.0 = free-flow)
    "shipment_weight_kg",           # kg  — quantity × ~2 kg/unit proxy
]


# ---------------------------------------------------------------------------
# Geo
# ---------------------------------------------------------------------------

def haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Return great-circle distance in **kilometres** between two WGS-84 points.

    Parameters
    ----------
    lat1, lon1 : float   Origin in decimal degrees.
    lat2, lon2 : float   Destination in decimal degrees.

    Returns
    -------
    float   Distance in km.

    Example
    -------
    >>> round(haversine_distance(51.5, -0.1, 48.85, 2.35))
    342
    """
    rl1 = math.radians(lat1);  rl2 = math.radians(lat2)
    dlo = math.radians(lon2 - lon1)
    dla = rl2 - rl1
    a = math.sin(dla / 2) ** 2 + math.cos(rl1) * math.cos(rl2) * math.sin(dlo / 2) ** 2
    return 2 * _EARTH_R_KM * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Traffic model
# ---------------------------------------------------------------------------

def traffic_factor(hour: Optional[int] = None) -> float:
    """Return a congestion multiplier in **[0.40, 1.0]**.

    Higher values mean faster travel (less congestion).
    Based on a simplified hour-of-day profile that mirrors typical
    rush-hour patterns.

    Parameters
    ----------
    hour : int or None
        Hour of day 0-23 in UTC.  If None, uses the current UTC hour.

    Returns
    -------
    float
        1.0   — free-flow (off-peak / night)
        0.60  — moderate traffic (shoulder periods)
        0.40  — heavy congestion (AM/PM peak)
    """
    if hour is None:
        hour = datetime.now(timezone.utc).hour

    if (7 <= hour <= 9) or (17 <= hour <= 19):
        return 0.40          # peak congestion
    if (10 <= hour <= 16) or (20 <= hour <= 21):
        return 0.75          # moderate
    return 1.00              # night / early morning — free-flow


# ---------------------------------------------------------------------------
# Vehicle helpers
# ---------------------------------------------------------------------------

def vehicle_speed_kmph(vehicle_type: str) -> float:
    """Look up nominal cruising speed for a vehicle type."""
    return VEHICLE_SPEEDS.get(vehicle_type, _DEFAULT_SPEED)


def vehicle_capacity_kg(vehicle_type: str) -> float:
    """Look up max payload capacity in kg for a vehicle type."""
    return VEHICLE_CAPACITIES.get(vehicle_type, _DEFAULT_CAPACITY)


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def build_feature_vector(
    vehicle: Dict[str, Any],
    shipment: Dict[str, Any],
) -> np.ndarray:
    """Build a (1, 6) feature matrix for ETA prediction.

    The feature order matches :data:`FEATURE_COLUMNS` exactly — the same
    order used when training the :class:`~ml_engine.eta_model.ETAModel`.

    Parameters
    ----------
    vehicle : dict
        Must contain: ``current_latitude``, ``current_longitude``,
        ``type`` (optional — defaults to "Truck").
    shipment : dict
        Must contain: ``warehouse_lat``, ``warehouse_lon``,
        ``destination_lat``, ``destination_lon``, ``quantity`` (units).
        Optional: ``weight_kg`` (overrides the quantity-based proxy).

    Returns
    -------
    np.ndarray, shape (1, 6)
        Float64 feature matrix ready to pass to ``model.predict()``.

    Raises
    ------
    KeyError
        If any required coordinate key is missing from the input dicts.
    """
    v_type = vehicle.get("type", "Truck")

    dist_v_to_src = haversine_distance(
        vehicle["current_latitude"], vehicle["current_longitude"],
        shipment["warehouse_lat"],   shipment["warehouse_lon"],
    )
    dist_src_to_dst = haversine_distance(
        shipment["warehouse_lat"],     shipment["warehouse_lon"],
        shipment["destination_lat"],   shipment["destination_lon"],
    )
    cap       = vehicle_capacity_kg(v_type)
    speed     = vehicle_speed_kmph(v_type)
    tf        = traffic_factor()
    # Weight proxy: if explicit weight_kg not supplied, assume 2 kg/unit
    weight_kg = float(
        shipment.get("weight_kg") or (shipment.get("quantity", 1) * 2.0)
    )

    return np.array(
        [[dist_v_to_src, dist_src_to_dst, cap, speed, tf, weight_kg]],
        dtype=np.float64,
    )


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

def generate_synthetic_training_data(
    n_samples: int = 2_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate a synthetic dataset for ETA model training.

    Each row represents a hypothetical dispatch scenario.  The target
    ``eta_hours`` is calculated deterministically from the features plus
    a small Gaussian noise term to simulate real measurement variance.

    Parameters
    ----------
    n_samples : int
        Number of rows to generate (default 2 000).
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    pd.DataFrame
        Columns: distance_vehicle_to_source, distance_source_to_dest,
                 vehicle_capacity_kg, vehicle_speed_kmph, traffic_factor,
                 shipment_weight_kg, **eta_hours** (target).

    Notes
    -----
    * Vehicle positions and warehouse/destination coordinates are drawn
      randomly over a ±60 ° lat/lon grid (covers most of Europe + Asia).
    * Vehicle types are sampled uniformly from the VEHICLE_SPEEDS registry.
    * Peak-hour traffic patterns are applied via :func:`traffic_factor` to
      a randomly sampled hour of day.
    * The true ETA formula:
      ``eta = (dist_v_src + dist_src_dst) / (speed × tf) + noise``
    """
    rng = np.random.default_rng(seed)
    random.seed(seed)

    v_types = list(VEHICLE_SPEEDS.keys())
    rows = []

    for _ in range(n_samples):
        # Random coordinates (Europe-scale lat/lon range)
        v_lat,   v_lon   = rng.uniform(-60, 60), rng.uniform(-60, 60)
        src_lat, src_lon = rng.uniform(-60, 60), rng.uniform(-60, 60)
        dst_lat, dst_lon = rng.uniform(-60, 60), rng.uniform(-60, 60)

        v_type = random.choice(v_types)
        speed  = vehicle_speed_kmph(v_type)
        cap    = vehicle_capacity_kg(v_type)
        hour   = int(rng.integers(0, 24))
        tf     = traffic_factor(hour)
        qty    = int(rng.integers(1, 500))
        wt     = qty * rng.uniform(1.5, 3.5)   # kg per unit varies

        d_vs  = haversine_distance(v_lat, v_lon, src_lat, src_lon)
        d_sd  = haversine_distance(src_lat, src_lon, dst_lat, dst_lon)

        # Ground-truth ETA: total distance ÷ effective speed, bounded ≥ 0.1 h
        eta = max(
            (d_vs + d_sd) / max(speed * tf, 1.0) + rng.normal(0, 0.1),
            0.1,
        )

        rows.append({
            "distance_vehicle_to_source": round(d_vs, 4),
            "distance_source_to_dest":    round(d_sd, 4),
            "vehicle_capacity_kg":        cap,
            "vehicle_speed_kmph":         speed,
            "traffic_factor":             round(tf, 4),
            "shipment_weight_kg":         round(wt, 2),
            "eta_hours":                  round(eta, 4),
        })

    df = pd.DataFrame(rows)
    logger.info(
        "generate_synthetic_training_data: %d rows  eta mean=%.2f h  std=%.2f h",
        len(df), df["eta_hours"].mean(), df["eta_hours"].std(),
    )
    return df


# ---------------------------------------------------------------------------
# Model persistence
# ---------------------------------------------------------------------------

def load_model(path: Path | str) -> Optional[Any]:
    """Load a pickled model from *path*.

    Returns the model object, or ``None`` when the file does not exist or
    cannot be deserialized.  Logs a warning on failure rather than raising.

    Parameters
    ----------
    path : Path or str
        File path to the ``.pkl`` file.

    Returns
    -------
    object or None
    """
    p = Path(path)
    if not p.exists():
        logger.debug("load_model: %s not found", p)
        return None
    try:
        with open(p, "rb") as fh:
            model = pickle.load(fh)
        logger.info("load_model: loaded %s from %s", type(model).__name__, p)
        return model
    except Exception as exc:
        logger.warning("load_model: failed to load %s — %s", p, exc)
        return None


def save_model(model: Any, path: Path | str) -> None:
    """Pickle *model* to *path*, creating parent directories if needed.

    Parameters
    ----------
    model : Any
        Trained scikit-learn estimator (or any picklable object).
    path : Path or str
        Destination file path (e.g. ``ml_engine/models/eta_model.pkl``).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as fh:
        pickle.dump(model, fh, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("save_model: saved %s to %s", type(model).__name__, p)
