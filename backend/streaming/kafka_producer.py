# backend/streaming/kafka_producer.py
#
# ---------------------------------------------------------------------------
# Kafka Producer
# ---------------------------------------------------------------------------
#
# Provides a thread-safe, lazily-initialised KafkaProducer instance and a
# single public function:
#
#   publish_event(topic: str, data: dict) → None
#
# Design decisions:
#   • Lazy init — the producer is created on first use, not on module import.
#     This means the FastAPI process starts even if Kafka is temporarily down
#     during a rolling restart.
#   • Module-level singleton — KafkaProducer is internally thread-safe.
#     Creating one instance per request would waste connections and memory.
#   • acks="all" — the broker only confirms delivery once all in-sync
#     replicas have written the message.  Prevents data loss on broker
#     failure.  Use acks=1 if you need lower latency and can tolerate rare
#     message loss.
#   • retries=5 + retry_backoff_ms=300 — automatically retries transient
#     network errors before raising an exception to the caller.
#   • linger_ms=10 — batches messages that arrive within 10 ms together,
#     reducing Kafka round-trips at the cost of marginal extra latency.
#   • compression_type="gzip" — transparently compresses message batches.
#     Reduces network bandwidth with no application-level changes required.
#   • JSON serialisation — human-readable, schema-flexible, and compatible
#     with all downstream consumers regardless of language.  For high-
#     throughput production use, consider Avro with Schema Registry.
#
# ---------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from kafka import KafkaProducer
from kafka.errors import KafkaError

from backend.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level producer singleton
# ---------------------------------------------------------------------------
# Protected by a lock so parallel FastAPI startup workers don't race.
_producer: KafkaProducer | None = None
_producer_lock = threading.Lock()


def _get_producer() -> KafkaProducer:
    """Return the shared KafkaProducer, creating it on first call.

    Raises ``KafkaError`` if the broker is unreachable after all retries so
    the caller can propagate a meaningful HTTP 503 rather than hanging.
    """
    global _producer

    if _producer is not None:
        return _producer

    with _producer_lock:
        # Double-checked locking: another thread may have initialised while
        # we were waiting for the lock.
        if _producer is not None:
            return _producer

        logger.info(
            "kafka_producer_init",
            extra={"bootstrap_servers": settings.kafka_bootstrap_servers},
        )

        _producer = KafkaProducer(
            # ----------------------------------------------------------------
            # Cluster connection
            # ----------------------------------------------------------------
            bootstrap_servers=settings.kafka_bootstrap_servers,

            # ----------------------------------------------------------------
            # Serialisation — encode every message value as UTF-8 JSON bytes.
            # ----------------------------------------------------------------
            value_serializer=lambda payload: json.dumps(payload).encode("utf-8"),

            # ----------------------------------------------------------------
            # Key serialisation — topic keys are used for partition routing.
            # If no key is supplied in publish_event(), the broker distributes
            # messages round-robin across partitions.
            # ----------------------------------------------------------------
            key_serializer=lambda k: k.encode("utf-8") if k else None,

            # ----------------------------------------------------------------
            # Delivery guarantees
            # acks="all" → leader + all in-sync replicas must acknowledge.
            # For a single-node dev cluster this is equivalent to acks=1.
            # ----------------------------------------------------------------
            acks="all",

            # ----------------------------------------------------------------
            # Retry policy
            # 5 retries with 300 ms back-off survive short broker unavailability
            # (e.g. leader election during a rolling restart).
            # ----------------------------------------------------------------
            retries=5,
            retry_backoff_ms=300,

            # ----------------------------------------------------------------
            # Batching & compression
            # linger_ms=10  — wait up to 10 ms to accumulate a batch.
            # compression_type="gzip" — compress batches before sending.
            # ----------------------------------------------------------------
            linger_ms=10,
            compression_type="gzip",

            # ----------------------------------------------------------------
            # Request timeout — raise KafkaTimeoutError if the broker doesn't
            # respond within 30 s.
            # ----------------------------------------------------------------
            request_timeout_ms=30_000,
        )

        logger.info("kafka_producer_ready")
        return _producer


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def publish_event(
    topic: str,
    data: dict[str, Any],
    *,
    key: str | None = None,
) -> None:
    """Publish a JSON event to a Kafka topic.

    Args:
        topic:  Kafka topic name, e.g. ``"vehicle-location-topic"``.
        data:   Python dict that will be JSON-serialised and sent as the
                message value.
        key:    Optional partition key (string).  Messages with the same key
                always land on the same partition, preserving per-key ordering
                (e.g. one partition per vehicle_id).

    Raises:
        KafkaError: If the message cannot be delivered after all retries.

    Example::

        publish_event(
            "vehicle-location-topic",
            {
                "vehicle_id": "TRUCK_102",
                "latitude": 23.0225,
                "longitude": 72.5714,
                "timestamp": "2026-03-04T10:30:00Z",
            },
            key="TRUCK_102",
        )

    Notes on Kafka topics::

        A *topic* is a named, partitioned, append-only log stored on the
        broker.  Producers write to the tail; consumers read from any offset.
        Topics are created automatically when first written to (if
        auto.create.topics.enable=true, Bitnami default) or explicitly via
        kafka-topics.sh / an AdminClient.

        Partitions enable parallelism: ``N`` partitions → ``N`` consumers in
        the same consumer group can read simultaneously without contention.
    """
    producer = _get_producer()

    try:
        future = producer.send(topic, value=data, key=key)

        # producer.send() is asynchronous.  .get() blocks until the broker
        # confirms receipt (or raises on timeout/error).  Remove .get() for
        # maximum throughput fire-and-forget semantics.
        record_metadata = future.get(timeout=10)

        logger.info(
            "kafka_event_published",
            extra={
                "topic": record_metadata.topic,
                "partition": record_metadata.partition,
                "offset": record_metadata.offset,
                "key": key,
            },
        )

    except KafkaError as exc:
        logger.exception(
            "kafka_publish_failed",
            extra={"topic": topic, "error": str(exc)},
        )
        raise


def close_producer() -> None:
    """Flush pending messages and close the producer.

    Call this during application shutdown (e.g. FastAPI ``shutdown`` event)
    to ensure no buffered messages are lost.
    """
    global _producer

    with _producer_lock:
        if _producer is not None:
            logger.info("kafka_producer_closing")
            _producer.flush()
            _producer.close()
            _producer = None
            logger.info("kafka_producer_closed")
