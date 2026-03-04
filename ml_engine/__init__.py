# ml_engine/__init__.py
#
# Public API for the ML routing engine.
#
# Quick-start
# ───────────
#   from ml_engine import assign_vehicle_ai
#
#   result = assign_vehicle_ai(
#       shipment={"warehouse_lat": 51.5, "warehouse_lon": -0.1,
#                 "destination_lat": 48.85, "destination_lon": 2.35,
#                 "quantity": 100},
#       vehicles=[
#           {"id": 1, "status": "Available", "type": "Truck",
#            "current_latitude": 51.4, "current_longitude": -0.2},
#       ],
#   )
#   # → {"best_vehicle_id": 1, "predicted_eta": 3.14, "candidates": [...]}
#
# The module re-exports RouteOptimizer and ETAModel for callers that need
# the full classes (e.g. Celery tasks, test fixtures).

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from ml_engine.eta_model import ETAModel, _DEFAULT_MODEL_PATH
from ml_engine.route_optimizer import RouteOptimizer
from ml_engine.utils import FEATURE_COLUMNS, build_feature_vector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton: loaded once on first call, shared across all
# requests in the same process (Celery worker / FastAPI startup).
# ---------------------------------------------------------------------------

_eta_model: Optional[ETAModel] = None


def _get_model() -> ETAModel:
    global _eta_model
    if _eta_model is None:
        _eta_model = ETAModel.load(_DEFAULT_MODEL_PATH)
        if _eta_model.is_trained:
            logger.info("assign_vehicle_ai: loaded trained ETAModel from %s", _DEFAULT_MODEL_PATH)
        else:
            logger.warning(
                "assign_vehicle_ai: no trained model at %s — using physics heuristic",
                _DEFAULT_MODEL_PATH,
            )
    return _eta_model


# ---------------------------------------------------------------------------
# assign_vehicle_ai — primary integration entry point
# ---------------------------------------------------------------------------

def assign_vehicle_ai(
    shipment: Dict[str, Any],
    vehicles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Select the best available vehicle for a shipment using ML-predicted ETA.

    Algorithm
    ─────────
    1. Filter *vehicles* to status == "Available".
    2. For each candidate, build the 6-component feature vector.
    3. Run feature matrix through ETAModel in a single batch call.
    4. Pick the vehicle with the **lowest** predicted ETA.
    5. Return a structured result dict.

    Falls back to the physics heuristic (distance / speed × traffic) when
    no trained model exists at ``ml_engine/models/eta_model.pkl``.

    Parameters
    ----------
    shipment : dict
        Must contain:
        - ``warehouse_lat``, ``warehouse_lon`` (float) — pickup coordinates
        - ``destination_lat``, ``destination_lon`` (float) — drop-off coordinates
        - ``quantity`` (float) — shipment weight in kg
    vehicles : list[dict]
        Each entry must contain:
        - ``id`` (int | str) — vehicle identifier
        - ``status`` (str) — ``"Available"`` to be considered
        - ``type`` (str) — ``"Truck"`` | ``"Van"`` | ``"Semi"`` |
          ``"Refrigerated"`` | ``"Bike"``
        - ``current_latitude``, ``current_longitude`` (float)

    Returns
    -------
    dict
        ``{
            "best_vehicle_id": int | str | None,
            "predicted_eta":   float,            # hours; NaN if no candidates
            "candidates": [                      # all Available vehicles, ranked
                {
                    "vehicle_id":    int | str,
                    "vehicle_type":  str,
                    "predicted_eta": float,
                },
                ...
            ],
        }``

    Raises
    ------
    ValueError
        If *shipment* is missing required coordinate or quantity fields.
    """
    # ── Validate shipment ──────────────────────────────────────────────────
    required_shipment = {
        "warehouse_lat", "warehouse_lon",
        "destination_lat", "destination_lon",
        "quantity",
    }
    missing = required_shipment - set(shipment)
    if missing:
        raise ValueError(f"assign_vehicle_ai: shipment is missing fields: {missing}")

    # ── Filter to available vehicles ───────────────────────────────────────
    available = [v for v in vehicles if str(v.get("status", "")).lower() == "available"]
    if not available:
        logger.warning("assign_vehicle_ai: no Available vehicles in pool of %d", len(vehicles))
        return {"best_vehicle_id": None, "predicted_eta": float("nan"), "candidates": []}

    # ── Build feature matrix (n × 6) in one shot ──────────────────────────
    try:
        features_list: List[np.ndarray] = [build_feature_vector(v, shipment) for v in available]
        X = np.vstack(features_list)  # shape (n_candidates, 6)
    except Exception as exc:
        logger.error("assign_vehicle_ai: feature construction failed — %s", exc)
        return {"best_vehicle_id": None, "predicted_eta": float("nan"), "candidates": []}

    # ── Predict ETAs ──────────────────────────────────────────────────────
    model  = _get_model()
    etas   = model.predict_batch(X)       # np.ndarray shape (n,)

    # ── Rank candidates ───────────────────────────────────────────────────
    ranked_idx = int(np.argmin(etas))

    candidates = [
        {
            "vehicle_id":    v["id"],
            "vehicle_type":  v.get("type", "Unknown"),
            "predicted_eta": round(float(etas[i]), 3),
        }
        for i, v in enumerate(available)
    ]
    # Sort by ETA for the caller's convenience
    candidates.sort(key=lambda c: c["predicted_eta"])

    best_vehicle_id  = available[ranked_idx]["id"]
    best_eta         = round(float(etas[ranked_idx]), 3)

    logger.debug(
        "assign_vehicle_ai: selected vehicle %s  ETA=%.3f h  "
        "from %d candidates",
        best_vehicle_id, best_eta, len(available),
    )

    return {
        "best_vehicle_id": best_vehicle_id,
        "predicted_eta":   best_eta,
        "candidates":      candidates,
    }


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "assign_vehicle_ai",
    "ETAModel",
    "RouteOptimizer",
    "FEATURE_COLUMNS",
]
