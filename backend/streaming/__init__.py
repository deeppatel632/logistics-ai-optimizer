# backend/streaming/__init__.py
#
# Real-time event streaming layer — Apache Kafka integration.
#
# This module provides two public objects:
#
#   publish_event(topic, data)   — thin wrapper around KafkaProducer
#   start_consumer(...)          — blocking consumer loop (run as a separate
#                                  process or background thread)
#
# Kafka is used to decouple the FastAPI request path from downstream
# consumers such as the route optimisation engine, ML prediction service,
# and analytics pipeline.  The API writes an event and returns immediately;
# consumers process it asynchronously at their own pace, enabling independent
# scaling of each consumer group without API throttling.

from backend.streaming.kafka_producer import publish_event
from backend.streaming.kafka_consumer import start_consumer

__all__ = ["publish_event", "start_consumer"]
