# backend/ml/models/inference_service.py
#
# ---------------------------------------------------------------------------
# Domain-level ML Inference Service  (Step 49)
# ---------------------------------------------------------------------------
#
# This module sits above model_client.py and provides business-logic functions
# that orchestrate the full inference pipeline:
#
#   1. Resolve entity features from the Feature Store
#   2. Build the Triton request payload
#   3. Call model_client.infer()
#   4. Parse and return the prediction
#
# Triton model registry (models deployed on the Triton server):
#
#   eta_model        — Predicts ETA for a shipment in hours.
#                      Inputs: distance (km), traffic_score, vehicle_speed (km/h)
#                      Output: eta_hours (float)
#
#   demand_model     — Predicts warehouse demand for the next 24 h.
#                      Inputs: warehouse_id (encoded), day_of_week, hour_of_day,
#                              on_time_rate, avg_daily_shipments
#                      Output: demand_units (float)
#
# ---------------------------------------------------------------------------

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.ml.models.model_client import (
    infer,
    build_fp32_input,
    extract_fp32_output,
    TritonClientError,
)
from backend.ml.features.feature_store import get_feature_vector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ETA Prediction
# ---------------------------------------------------------------------------

# Names of the features expected by eta_model's INPUT0 tensor.
# MUST match the order in the model's config.pbtxt.
_ETA_FEATURE_NAMES = ["distance", "traffic_score", "vehicle_speed"]
_ETA_MODEL = "eta_model"


def predict_eta(input_data: dict[str, float]) -> float:
    """Predict shipment ETA in hours.

    Accepts a flat dict of feature values for a *single* inference request.
    Internally calls the Triton ``eta_model`` via the HTTP v2 API.

    Args:
        input_data: Dict with keys matching ``_ETA_FEATURE_NAMES``:

            .. code-block:: python

                {
                    "distance":      120.5,   # km
                    "traffic_score": 0.65,    # 0-1
                    "vehicle_speed": 70.0,    # km/h
                }

    Returns:
        Predicted ETA in hours (float).

    Raises:
        TritonClientError: If Triton is unavailable or returns an error.
        ValueError:        If required feature keys are missing.

    Example::

        eta = predict_eta({
            "distance": 120.5,
            "traffic_score": 0.65,
            "vehicle_speed": 70.0,
        })
        print(f"Estimated arrival in {eta:.1f} hours")
    """
    _validate_features(input_data, _ETA_FEATURE_NAMES)

    row = [input_data[name] for name in _ETA_FEATURE_NAMES]

    logger.info(
        "eta_prediction_request",
        extra={"features": input_data},
    )

    response = infer(
        model_name=_ETA_MODEL,
        inputs=[build_fp32_input("INPUT0", [row])],
        outputs=[{"name": "OUTPUT0"}],
    )

    eta_hours = extract_fp32_output(response)[0][0]

    logger.info(
        "eta_prediction_result",
        extra={"eta_hours": eta_hours, "features": input_data},
    )

    return float(eta_hours)


def predict_eta_from_entity(vehicle_id: str, route_distance_km: float) -> float:
    """Convenience wrapper: fetch live features from the Feature Store and predict ETA.

    Uses real-time ``vehicle_speed`` and ``traffic_score`` from the Feature
    Store (sourced from Kafka vehicle-location events) together with the
    supplied ``route_distance_km``.

    Args:
        vehicle_id:         Entity ID for Feature Store lookup, e.g. ``"TRUCK_102"``.
        route_distance_km:  Pre-computed route distance (km).

    Returns:
        Predicted ETA in hours.

    Notes:
        If ``vehicle_speed`` or ``traffic_score`` is missing from the Feature
        Store (entity never seen), sensible defaults are used so inference
        does not fail hard.  Callers can log a warning upstream.
    """
    vector = get_feature_vector(
        entity_id=vehicle_id,
        feature_names=["vehicle_speed", "traffic_score"],
    )

    vehicle_speed = vector.get("vehicle_speed") or 60.0    # default 60 km/h
    traffic_score = vector.get("traffic_score") or 0.4     # default moderate

    return predict_eta({
        "distance": route_distance_km,
        "traffic_score": traffic_score,
        "vehicle_speed": vehicle_speed,
    })


# ---------------------------------------------------------------------------
# Demand Prediction
# ---------------------------------------------------------------------------

_DEMAND_FEATURE_NAMES = [
    "warehouse_id_encoded",
    "day_of_week",
    "hour_of_day",
    "on_time_rate",
    "avg_daily_shipments",
]
_DEMAND_MODEL = "demand_model"


def predict_demand(input_data: dict[str, float]) -> float:
    """Predict demand units for a warehouse in the next 24 hours.

    Args:
        input_data: Dict with keys matching ``_DEMAND_FEATURE_NAMES``:

            .. code-block:: python

                {
                    "warehouse_id_encoded":  3.0,   # ordinal-encoded warehouse id
                    "day_of_week":           2.0,   # 0=Mon, 6=Sun
                    "hour_of_day":           9.0,   # 0-23
                    "on_time_rate":          0.92,  # 0-1
                    "avg_daily_shipments":   450.0,
                }

    Returns:
        Predicted demand in units (float — round for integer demand).
    """
    _validate_features(input_data, _DEMAND_FEATURE_NAMES)

    row = [input_data[name] for name in _DEMAND_FEATURE_NAMES]

    response = infer(
        model_name=_DEMAND_MODEL,
        inputs=[build_fp32_input("INPUT0", [row])],
        outputs=[{"name": "OUTPUT0"}],
    )

    return float(extract_fp32_output(response)[0][0])


# ---------------------------------------------------------------------------
# Batch Inference
# ---------------------------------------------------------------------------

def batch_predict_eta(batch: list[dict[str, float]]) -> list[float]:
    """Run ETA prediction for a list of input dicts in a single Triton call.

    Sending a batch is significantly more efficient than N individual calls:
      • Reduces HTTP round-trips
      • Allows Triton to use GPU tensor cores for vectorised inference
      • Reduces per-request overhead (auth, routing, serialisation)

    Args:
        batch: List of input dicts (same schema as ``predict_eta``).
               Up to 256 rows recommended; larger batches may exceed Triton's
               ``max_batch_size`` configured in config.pbtxt.

    Returns:
        List of ETA predictions (hours), in the same order as ``batch``.

    Example::

        results = batch_predict_eta([
            {"distance": 100.0, "traffic_score": 0.3, "vehicle_speed": 80.0},
            {"distance": 250.0, "traffic_score": 0.8, "vehicle_speed": 45.0},
        ])
        # [1.25, 5.56]
    """
    if not batch:
        return []

    for item in batch:
        _validate_features(item, _ETA_FEATURE_NAMES)

    rows = [[item[name] for name in _ETA_FEATURE_NAMES] for item in batch]

    logger.info(
        "batch_eta_prediction_request",
        extra={"batch_size": len(rows)},
    )

    response = infer(
        model_name=_ETA_MODEL,
        inputs=[build_fp32_input("INPUT0", rows)],
        outputs=[{"name": "OUTPUT0"}],
    )

    raw_outputs = extract_fp32_output(response)

    # Output shape: [batch_size, 1]  — flatten to [batch_size]
    return [float(row[0]) for row in raw_outputs]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_features(data: dict[str, Any], required: list[str]) -> None:
    """Raise ValueError if any required feature key is absent from data."""
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(
            f"Missing required feature(s) for inference: {missing}. "
            f"Provided keys: {list(data.keys())}"
        )
