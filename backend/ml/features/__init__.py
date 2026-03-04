# backend/ml/features/__init__.py
#
# Feature Store sub-package.
#
# The feature store provides a thin abstraction layer between raw operational
# data (SQL records, Kafka events) and the ML models that consume it.
# Storing features separately from raw data:
#
#   1. Ensures training and inference use *identical* feature transforms
#      (eliminates training-serving skew).
#   2. Allows offline batch computation of expensive features (e.g. 7-day
#      rolling averages) that are then served in < 1 ms at inference time.
#   3. Provides an audit trail for every feature value used in a prediction.
#
# Two storage tiers are used:
#   • SQL (Azure SQL Edge)  — durable, queryable, used for training datasets.
#   • Redis                 — low-latency cache in front of SQL, used for
#                             real-time inference (< 5 ms read path).

from backend.ml.features.feature_store import (
    store_feature,
    get_feature,
    get_feature_vector,
    list_entity_features,
    delete_feature,
)

__all__ = [
    "store_feature",
    "get_feature",
    "get_feature_vector",
    "list_entity_features",
    "delete_feature",
]
