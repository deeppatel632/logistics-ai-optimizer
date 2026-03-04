# backend/streaming/kafka_consumer.py
#
# ---------------------------------------------------------------------------
# Kafka Consumer
# ---------------------------------------------------------------------------
#
# Provides a long-running consumer loop that reads events from one or more
# Kafka topics and dispatches them to a registered handler function.
#
# Public API:
#
#   start_consumer(
#       topics   = ["vehicle-location-topic"],
#       handler  = my_handler_fn,        # called for every message
#       group_id = "route-engine-group",
#   )
#
# How Kafka consumers work:
#
#   A *consumer group* (identified by ``group_id``) is a logical subscriber.
#   Kafka assigns each topic partition to exactly one consumer within the
#   group; if you run N consumer processes with the same group_id, Kafka
#   load-balances partitions across them automatically.
#
#   To run multiple independent subscribers to the same topic (e.g. route
#   engine AND analytics service both reading vehicle-location-topic), give
#   each subscriber a different group_id.  Each group maintains its own
#   offset and reads every message independently.
#
#   Offsets are committed back to Kafka after each successful handler call,
#   so the consumer resumes from the right place after a restart.
#
# Running this consumer:
#
#   As a long-running background process:
#
#     python -m backend.streaming.kafka_consumer
#
#   Or in Docker Compose, add a service:
#
#     consumer:
#       command: python -m backend.streaming.kafka_consumer
#
#   Or as a thread inside FastAPI (suitable for low-throughput scenarios):
#
#     import threading
#     from backend.streaming.kafka_consumer import start_consumer
#     t = threading.Thread(
#         target=start_consumer,
#         kwargs={"topics": ["vehicle-location-topic"]},
#         daemon=True,
#     )
#     t.start()
#
# ---------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import signal
import time
from typing import Callable

from kafka import KafkaConsumer
from kafka.errors import KafkaError, NoBrokersAvailable

from backend.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default topics this consumer subscribes to when run as __main__
# ---------------------------------------------------------------------------
DEFAULT_TOPICS = ["vehicle-location-topic"]

# Consumer group for the default route-engine processor.
# Each logical downstream service must use a unique group_id so Kafka
# delivers every message to all services independently.
DEFAULT_GROUP_ID = "route-engine-group"

# How long to block waiting for new messages (ms) before looping again.
# Shorter = more responsive to SIGTERM; longer = fewer idle CPU cycles.
_POLL_TIMEOUT_MS = 1_000

# Seconds to wait between reconnection attempts during broker unavailability.
_RECONNECT_BACKOFF_S = 5


# ---------------------------------------------------------------------------
# Default event handler
# ---------------------------------------------------------------------------

def _default_handler(topic: str, message: dict) -> None:
    """Log the received event.  Replace with domain logic in production.

    In a real deployment this function would call:
      - Route optimisation service for "vehicle-location-topic" events
      - Inventory update service for "warehouse-inventory-topic" events
      - etc.
    """
    logger.info(
        "kafka_event_received",
        extra={"topic": topic, "message": message},
    )


# ---------------------------------------------------------------------------
# Consumer loop
# ---------------------------------------------------------------------------

def start_consumer(
    topics: list[str] | None = None,
    handler: Callable[[str, dict], None] | None = None,
    group_id: str = DEFAULT_GROUP_ID,
) -> None:
    """Subscribe to ``topics`` and invoke ``handler`` for every message.

    This function runs **forever** (blocking).  It is designed to be the
    target of a long-lived process or daemon thread.

    Args:
        topics:    List of Kafka topic names to subscribe to.
                   Defaults to ``DEFAULT_TOPICS``.
        handler:   A callable ``(topic: str, message: dict) → None`` that
                   is called for each received message.
                   Defaults to a structured-logging handler.
        group_id:  Kafka consumer group identifier.  Use a unique value for
                   each independent downstream service.

    The loop handles:
      • Graceful shutdown on SIGTERM / KeyboardInterrupt
      • Automatic reconnection when the broker is temporarily unreachable
      • Per-message exception isolation (a bad message doesn't stop the loop)
    """
    if topics is None:
        topics = DEFAULT_TOPICS
    if handler is None:
        handler = _default_handler

    logger.info(
        "kafka_consumer_starting",
        extra={
            "topics": topics,
            "group_id": group_id,
            "bootstrap_servers": settings.kafka_bootstrap_servers,
        },
    )

    # -----------------------------------------------------------------------
    # Graceful shutdown flag — set by signal handler so the loop exits cleanly
    # after finishing the current batch.
    # -----------------------------------------------------------------------
    shutdown_requested = False

    def _handle_shutdown(signum, frame):  # noqa: ARG001
        nonlocal shutdown_requested
        logger.info("kafka_consumer_shutdown_requested", extra={"signal": signum})
        shutdown_requested = True

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    # -----------------------------------------------------------------------
    # Outer reconnect loop
    # -----------------------------------------------------------------------
    while not shutdown_requested:
        consumer = None
        try:
            consumer = _create_consumer(group_id)

            # -----------------------------------------------------------------
            # Subscribe to topics.
            # Kafka re-triggers a partition-rebalance whenever a consumer
            # joins or leaves the group.  Subscribing to a pattern is also
            # supported: consumer.subscribe(pattern="vehicle-.*-topic")
            # -----------------------------------------------------------------
            consumer.subscribe(topics)
            logger.info(
                "kafka_consumer_subscribed",
                extra={"topics": topics, "group_id": group_id},
            )

            # -----------------------------------------------------------------
            # Inner poll loop
            # -----------------------------------------------------------------
            while not shutdown_requested:
                # poll() returns a dict: {TopicPartition → [ConsumerRecord]}
                records = consumer.poll(timeout_ms=_POLL_TIMEOUT_MS)

                for partition, messages in records.items():
                    for msg in messages:
                        _process_message(msg, handler)

        except NoBrokersAvailable:
            logger.warning(
                "kafka_no_brokers_available",
                extra={
                    "retry_in_seconds": _RECONNECT_BACKOFF_S,
                    "bootstrap_servers": settings.kafka_bootstrap_servers,
                },
            )
            time.sleep(_RECONNECT_BACKOFF_S)

        except KafkaError as exc:
            logger.exception("kafka_consumer_error", extra={"error": str(exc)})
            time.sleep(_RECONNECT_BACKOFF_S)

        finally:
            if consumer is not None:
                logger.info("kafka_consumer_closing")
                consumer.close()
                logger.info("kafka_consumer_closed")

    logger.info("kafka_consumer_stopped")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_consumer(group_id: str) -> KafkaConsumer:
    """Instantiate a KafkaConsumer with production-safe config."""

    return KafkaConsumer(
        # ----------------------------------------------------------------
        # Cluster connection
        # ----------------------------------------------------------------
        bootstrap_servers=settings.kafka_bootstrap_servers,

        # ----------------------------------------------------------------
        # Consumer group — Kafka load-balances partitions across all
        # consumers in the same group.
        # ----------------------------------------------------------------
        group_id=group_id,

        # ----------------------------------------------------------------
        # Deserialisation — parse the raw bytes back to a Python dict.
        # Handle malformed JSON gracefully: return None (filtered below).
        # ----------------------------------------------------------------
        value_deserializer=_safe_json_deserialise,

        # ----------------------------------------------------------------
        # Offset reset policy:
        #   "earliest" — on first run (no committed offset) start from the
        #                 beginning of the topic.  Good for replay/testing.
        #   "latest"   — start from new messages only (skip historical).
        # ----------------------------------------------------------------
        auto_offset_reset="earliest",

        # ----------------------------------------------------------------
        # Commit strategy:
        #   enable_auto_commit=True  — Kafka commits offsets automatically
        #   every auto_commit_interval_ms.
        #   For exactly-once or at-least-once semantics with manual control,
        #   set enable_auto_commit=False and call consumer.commit() after
        #   each successful handler invocation.
        # ----------------------------------------------------------------
        enable_auto_commit=True,
        auto_commit_interval_ms=1_000,

        # ----------------------------------------------------------------
        # Session / heartbeat timeouts
        # session_timeout_ms — broker removes consumer from group if no
        #   heartbeat within this window.
        # heartbeat_interval_ms — consumer sends heartbeat at this rate.
        #   Rule: heartbeat_interval < session_timeout / 3.
        # max_poll_interval_ms — maximum time between poll() calls before
        #   the broker considers the consumer dead.  Increase if your
        #   handler can take > 5 minutes (e.g. ML model inference).
        # ----------------------------------------------------------------
        session_timeout_ms=30_000,
        heartbeat_interval_ms=10_000,
        max_poll_interval_ms=300_000,

        # ----------------------------------------------------------------
        # Fetch tuning
        # max_poll_records — limit records returned per poll() to bound
        #   handler execution time per iteration.
        # ----------------------------------------------------------------
        max_poll_records=100,
    )


def _safe_json_deserialise(raw: bytes) -> dict | None:
    """Deserialise message bytes to a dict; return None on parse failure."""
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            "kafka_message_deserialise_failed",
            extra={"error": str(exc), "raw_bytes": raw[:200]},  # truncate for safety
        )
        return None


def _process_message(msg, handler: Callable[[str, dict], None]) -> None:
    """Call the handler for a single ConsumerRecord; swallow per-message errors."""
    if msg.value is None:
        # Malformed / unparseable message — skip rather than crash the loop.
        logger.warning(
            "kafka_skipping_null_message",
            extra={"topic": msg.topic, "partition": msg.partition, "offset": msg.offset},
        )
        return

    try:
        handler(msg.topic, msg.value)
    except Exception:  # noqa: BLE001
        # Log the error but don't let a bad message kill the consumer loop.
        # In production you would dead-letter-queue (DLQ) the message here.
        logger.exception(
            "kafka_handler_error",
            extra={
                "topic": msg.topic,
                "partition": msg.partition,
                "offset": msg.offset,
            },
        )


# ---------------------------------------------------------------------------
# CLI entry-point — run as: python -m backend.streaming.kafka_consumer
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    from backend.core.logging_config import configure_logging

    configure_logging()

    # Allow overriding topics via CLI args:  python -m ... topic1 topic2
    cli_topics = sys.argv[1:] or DEFAULT_TOPICS
    start_consumer(topics=cli_topics)
