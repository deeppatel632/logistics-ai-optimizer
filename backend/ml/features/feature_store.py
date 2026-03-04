# backend/ml/features/feature_store.py
#
# ---------------------------------------------------------------------------
# Feature Store  (Step 48)
# ---------------------------------------------------------------------------
#
# Architecture overview
# ─────────────────────
#
#                        ┌─────────────────────────────┐
#  Kafka consumer        │  store_feature(entity, name, │
#  Celery worker      ─► │  value)                      │
#  REST endpoint         └──────────┬──────────────────┘
#                                   │
#                      ┌────────────┴──────────────┐
#                      │                           │
#               SQL (durable)              Redis (cache)
#               ml_features table         HSET ml:feat:<entity>
#               (queryable for            (< 2 ms read for
#                training exports)         online inference)
#                                   │
#                        ┌──────────┴──────────────┐
#  Inference path     ◄─ │  get_feature / get_      │
#  (< 5 ms)              │  feature_vector          │
#                        └──────────────────────────┘
#
# Database model: `ml_features` table  (see Alembic migration)
#
# Columns:
#   entity_id     — the object this feature belongs to, e.g. "TRUCK_102",
#                   "ROUTE_77", "WH_5"
#   feature_name  — e.g. "vehicle_speed", "traffic_score"
#   value         — stored as FLOAT.  Categorical features should be
#                   ordinal-encoded before storing.
#   updated_at    — last write timestamp; used by training jobs to pull
#                   features changed since the last export.
#   created_at    — immutable insert timestamp.
#
# Well-known feature names (document here to avoid typos across callers)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Vehicle features:
#   vehicle_speed        km/h — current GPS-derived speed
#   vehicle_load_ratio   0-1  — carried weight / max capacity
#
# Route features:
#   route_distance       km
#   traffic_score        0-1  (0 = free flow, 1 = gridlock)
#   route_congestion     0-1  — historical average for this route segment
#
# Delivery features:
#   delivery_delay       hours — actual minus scheduled arrival
#   on_time_rate         0-1   — rolling 30-day on-time delivery %
#
# ---------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.connection import PrimarySessionLocal, ReplicaSessionLocal
from backend.core.redis_client import redis_client as _redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis cache configuration
# ---------------------------------------------------------------------------
# Cache TTL: 60 seconds.  Feature values are typically updated every few
# seconds from Kafka events; 60 s is a reasonable staleness bound for
# online inference without hammering the DB.
_CACHE_TTL_SECONDS = 60

# Redis key prefix — avoids collisions with other Redis namespaces.
_KEY_PREFIX = "ml:feat"


def _cache_key(entity_id: str, feature_name: str) -> str:
    """Build a Redis hash key for a feature value."""
    return f"{_KEY_PREFIX}:{entity_id}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def store_feature(
    entity_id: str,
    feature_name: str,
    value: float,
    db: Session | None = None,
) -> None:
    """Persist a feature value to SQL and invalidate the Redis cache entry.

    Args:
        entity_id:    Identifier for the entity, e.g. ``"TRUCK_102"``,
                      ``"ROUTE_77"``, ``"WH_5"``.
        feature_name: Feature name, e.g. ``"vehicle_speed"``.
        value:        Numeric feature value.
        db:           Optional write session.  If not supplied, one is opened
                      and closed internally; pass an existing session to
                      participate in the caller's transaction.

    Notes:
        Uses an UPSERT pattern (MERGE on SQL Server) so repeated writes for
        the same ``(entity_id, feature_name)`` pair update the existing row
        rather than inserting duplicates.
    """
    _close_session = db is None
    if db is None:
        db = PrimarySessionLocal()

    try:
        now = datetime.now(timezone.utc)

        # MERGE is SQL Server's UPSERT syntax.
        # On other databases substitute INSERT … ON CONFLICT DO UPDATE.
        db.execute(
            text(
                """
                MERGE ml_features AS target
                USING (SELECT :entity_id AS entity_id,
                              :feature_name AS feature_name) AS source
                ON  target.entity_id    = source.entity_id
                AND target.feature_name = source.feature_name
                WHEN MATCHED THEN
                    UPDATE SET value      = :value,
                               updated_at = :now
                WHEN NOT MATCHED THEN
                    INSERT (entity_id, feature_name, value, updated_at, created_at)
                    VALUES (:entity_id, :feature_name, :value, :now, :now);
                """
            ),
            {
                "entity_id": entity_id,
                "feature_name": feature_name,
                "value": float(value),
                "now": now,
            },
        )
        db.commit()

        # Invalidate the Redis cache so the next read fetches the fresh value.
        _invalidate_cache(entity_id, feature_name)

        logger.debug(
            "feature_stored",
            extra={
                "entity_id": entity_id,
                "feature_name": feature_name,
                "value": value,
            },
        )

    except Exception:
        db.rollback()
        logger.exception(
            "feature_store_write_failed",
            extra={"entity_id": entity_id, "feature_name": feature_name},
        )
        raise
    finally:
        if _close_session:
            db.close()


def get_feature(
    entity_id: str,
    feature_name: str,
    db: Session | None = None,
) -> float | None:
    """Retrieve a single feature value.

    Read path (fast):
      1. Check Redis cache — return immediately if present (< 2 ms).
      2. Fall back to SQL replica — populate cache for subsequent reads.

    Returns:
        The stored float value, or ``None`` if the feature has never been
        written for this entity.
    """
    # 1. Cache hit
    cached = _read_cache(entity_id, feature_name)
    if cached is not None:
        return cached

    # 2. SQL read
    _close_session = db is None
    if db is None:
        db = ReplicaSessionLocal()

    try:
        row = db.execute(
            text(
                """
                SELECT value
                FROM   ml_features
                WHERE  entity_id    = :entity_id
                AND    feature_name = :feature_name
                """
            ),
            {"entity_id": entity_id, "feature_name": feature_name},
        ).fetchone()

        if row is None:
            return None

        value = float(row[0])

        # Populate cache for next inference call.
        _write_cache(entity_id, feature_name, value)

        return value

    finally:
        if _close_session:
            db.close()


def get_feature_vector(
    entity_id: str,
    feature_names: list[str],
    db: Session | None = None,
) -> dict[str, float | None]:
    """Retrieve multiple features for the same entity in a single DB query.

    This is the primary entry point for ML inference — callers request all
    features needed for a model in one call, which executes as a single
    ``WHERE … IN (…)`` SQL query rather than N individual lookups.

    Returns:
        Dict mapping ``feature_name → value`` (``None`` for missing features).

    Example::

        vector = get_feature_vector(
            "TRUCK_102",
            ["vehicle_speed", "route_distance", "traffic_score", "delivery_delay"],
        )
        # {"vehicle_speed": 72.3, "route_distance": 145.0,
        #  "traffic_score": 0.42, "delivery_delay": None}
    """
    if not feature_names:
        return {}

    result: dict[str, float | None] = {name: None for name in feature_names}
    missing_names: list[str] = []

    # Check Redis cache for each feature.
    for name in feature_names:
        cached = _read_cache(entity_id, name)
        if cached is not None:
            result[name] = cached
        else:
            missing_names.append(name)

    if not missing_names:
        return result  # full cache hit

    # Batch-fetch missing features from SQL.
    _close_session = db is None
    if db is None:
        db = ReplicaSessionLocal()

    try:
        placeholders = ", ".join(f":fn{i}" for i in range(len(missing_names)))
        params: dict[str, Any] = {"entity_id": entity_id}
        for i, name in enumerate(missing_names):
            params[f"fn{i}"] = name

        rows = db.execute(
            text(
                f"""
                SELECT feature_name, value
                FROM   ml_features
                WHERE  entity_id    = :entity_id
                AND    feature_name IN ({placeholders})
                """
            ),
            params,
        ).fetchall()

        for row in rows:
            feat_name, val = row[0], float(row[1])
            result[feat_name] = val
            _write_cache(entity_id, feat_name, val)

        return result

    finally:
        if _close_session:
            db.close()


def list_entity_features(
    entity_id: str,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """Return all feature rows for an entity (used for debugging / auditing).

    Returns:
        List of dicts with keys: ``feature_name``, ``value``, ``updated_at``.
    """
    _close_session = db is None
    if db is None:
        db = ReplicaSessionLocal()

    try:
        rows = db.execute(
            text(
                """
                SELECT feature_name, value, updated_at
                FROM   ml_features
                WHERE  entity_id = :entity_id
                ORDER  BY feature_name
                """
            ),
            {"entity_id": entity_id},
        ).fetchall()

        return [
            {
                "feature_name": row[0],
                "value": float(row[1]),
                "updated_at": row[2].isoformat() if row[2] else None,
            }
            for row in rows
        ]

    finally:
        if _close_session:
            db.close()


def delete_feature(
    entity_id: str,
    feature_name: str,
    db: Session | None = None,
) -> None:
    """Hard-delete a feature row (use sparingly — prefer updating to 0/null)."""
    _close_session = db is None
    if db is None:
        db = PrimarySessionLocal()

    try:
        db.execute(
            text(
                """
                DELETE FROM ml_features
                WHERE  entity_id    = :entity_id
                AND    feature_name = :feature_name
                """
            ),
            {"entity_id": entity_id, "feature_name": feature_name},
        )
        db.commit()
        _invalidate_cache(entity_id, feature_name)

    except Exception:
        db.rollback()
        raise
    finally:
        if _close_session:
            db.close()


# ---------------------------------------------------------------------------
# Redis cache helpers (private)
# ---------------------------------------------------------------------------

def _read_cache(entity_id: str, feature_name: str) -> float | None:
    try:
        raw = _redis.hget(_cache_key(entity_id, feature_name), feature_name)
        if raw is None:
            return None
        return float(raw)
    except Exception as exc:
        # Cache is best-effort — fall through to SQL on any error.
        logger.warning(
            "feature_cache_read_failed",
            extra={"entity_id": entity_id, "feature_name": feature_name, "error": str(exc)},
        )
        return None


def _write_cache(entity_id: str, feature_name: str, value: float) -> None:
    try:
        key = _cache_key(entity_id, feature_name)
        _redis.hset(key, feature_name, str(value))
        _redis.expire(key, _CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning(
            "feature_cache_write_failed",
            extra={"entity_id": entity_id, "feature_name": feature_name, "error": str(exc)},
        )


def _invalidate_cache(entity_id: str, feature_name: str) -> None:
    try:
        _redis.hdel(_cache_key(entity_id, feature_name), feature_name)
    except Exception as exc:
        logger.warning(
            "feature_cache_invalidate_failed",
            extra={"entity_id": entity_id, "feature_name": feature_name, "error": str(exc)},
        )
