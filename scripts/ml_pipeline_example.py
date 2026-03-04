# scripts/ml_pipeline_example.py
#
# ---------------------------------------------------------------------------
# End-to-end ML Pipeline Example
# ---------------------------------------------------------------------------
#
# This script demonstrates the full ML platform integrated pipeline:
#
#   ┌─────────────────────────────────────────────────────────────────────┐
#   │                     ML Platform Data Flow                           │
#   │                                                                     │
#   │  Kafka events                                                       │
#   │  (vehicle-location-topic)                                           │
#   │       │                                                             │
#   │       ▼                                                             │
#   │  Feature Store        ── store vehicle_speed, traffic_score ──►    │
#   │  (SQL + Redis)                                                      │
#   │       │                                                             │
#   │       ├──► Triton Inference Server                                  │
#   │       │    predict_eta(distance, traffic_score, vehicle_speed)      │
#   │       │         │                                                   │
#   │       │         ▼                                                   │
#   │       │   ETA prediction returned to API caller                    │
#   │       │                                                             │
#   │       └──► MinIO Data Lake                                          │
#   │            (training exports, model artefacts)                     │
#   │                 │                                                   │
#   │                 ▼                                                   │
#   │            Celery Training Job                                      │
#   │            download → train → upload artefact                      │
#   └─────────────────────────────────────────────────────────────────────┘
#
# Run:
#   python scripts/ml_pipeline_example.py
#
# All external services (SQL, Redis, MinIO, Triton) must be running.
# Use docker-compose.prod.yml to start them.
# ---------------------------------------------------------------------------

from __future__ import annotations

import json
import logging
import pathlib
import tempfile
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ml_pipeline_example")


# ---------------------------------------------------------------------------
# Step 1 — Feature Store: write features arriving from Kafka events
# ---------------------------------------------------------------------------

def step1_feature_ingestion():
    """Simulate a Kafka consumer handler writing features to the Feature Store.

    In production this is called inside ``start_consumer()`` with a handler
    that processes messages from ``vehicle-location-topic``.
    """
    from backend.ml.features.feature_store import store_feature

    logger.info("=== Step 1: Feature ingestion from Kafka event ===")

    # This data would normally come from a deserialized Kafka message:
    kafka_event = {
        "vehicle_id": "TRUCK_102",
        "latitude":    23.0225,
        "longitude":   72.5714,
        "speed_kmh":   72.3,
        "timestamp":   "2026-03-04T10:30:00Z",
        # traffic_score derived externally (e.g. HERE Maps API):
        "traffic_score": 0.42,
    }

    entity_id = kafka_event["vehicle_id"]

    # Write individual features to the store.
    store_feature(entity_id, "vehicle_speed",  kafka_event["speed_kmh"])
    store_feature(entity_id, "traffic_score",  kafka_event["traffic_score"])

    # Write static / computed route features (normally from a route-planning service):
    store_feature(entity_id, "route_distance",  145.0)   # km
    store_feature(entity_id, "delivery_delay",    0.25)  # hours late on last trip

    logger.info("Features stored for entity '%s'", entity_id)
    return entity_id


# ---------------------------------------------------------------------------
# Step 2 — Inference: predict ETA using Feature Store + Triton
# ---------------------------------------------------------------------------

def step2_eta_prediction(entity_id: str):
    """Read live features from the Feature Store and get ETA from Triton."""
    from backend.ml.features.feature_store import get_feature_vector
    from backend.ml.models.inference_service import predict_eta, batch_predict_eta
    from backend.ml.models.model_client import TritonClientError

    logger.info("=== Step 2: ETA prediction via Triton ===")

    # Fetch all features needed for the ETA model in a single DB roundtrip.
    vector = get_feature_vector(
        entity_id=entity_id,
        feature_names=["vehicle_speed", "traffic_score", "route_distance"],
    )
    logger.info("Feature vector: %s", vector)

    features = {
        "distance":      vector.get("route_distance") or 145.0,
        "traffic_score": vector.get("traffic_score")  or 0.4,
        "vehicle_speed": vector.get("vehicle_speed")  or 60.0,
    }

    try:
        eta = predict_eta(features)
        logger.info("Single-record ETA: %.2f hours", eta)
    except TritonClientError as exc:
        # Triton may not be running in this example environment.
        logger.warning("Triton unavailable (%s) — skipping inference step", exc)
        eta = None

    # Demonstrate batch inference for a fleet of vehicles.
    batch = [
        {"distance":  100.0, "traffic_score": 0.30, "vehicle_speed": 80.0},
        {"distance":  250.0, "traffic_score": 0.80, "vehicle_speed": 45.0},
        {"distance":   50.0, "traffic_score": 0.10, "vehicle_speed": 95.0},
    ]

    try:
        batch_results = batch_predict_eta(batch)
        for i, (inp, hours) in enumerate(zip(batch, batch_results)):
            logger.info(
                "Batch[%d]: distance=%.0f km  traffic=%.2f  →  ETA %.2f h",
                i, inp["distance"], inp["traffic_score"], hours,
            )
    except TritonClientError as exc:
        logger.warning("Batch inference skipped: %s", exc)

    return eta


# ---------------------------------------------------------------------------
# Step 3 — Data Lake: export features & upload to MinIO
# ---------------------------------------------------------------------------

def step3_data_lake_export():
    """Export the feature table to Parquet and upload to MinIO.

    In production this runs as a nightly Celery beat task.
    Here we write a tiny CSV to demonstrate the upload / download cycle.
    """
    from backend.storage.data_lake import (
        upload_training_data,
        download_training_data,
        create_bucket_if_missing,
        list_objects,
    )
    from botocore.exceptions import ClientError

    logger.info("=== Step 3: Data lake export / download ===")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"vehicle_features_{today}.csv"

    # Create a tiny in-memory training dataset.
    csv_content = (
        "entity_id,vehicle_speed,traffic_score,route_distance,delivery_delay\n"
        "TRUCK_102,72.3,0.42,145.0,0.25\n"
        "TRUCK_103,58.0,0.65,220.0,1.10\n"
        "TRUCK_104,85.5,0.18,88.0,-0.30\n"
    )

    try:
        create_bucket_if_missing()
    except ClientError as exc:
        logger.warning("MinIO unavailable (%s) — skipping data lake step", exc)
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        local_file = pathlib.Path(tmpdir) / filename
        local_file.write_text(csv_content)

        # Upload to training/ prefix.
        key = upload_training_data(local_file, object_name=filename)
        logger.info("Uploaded to MinIO: %s", key)

        # List objects to confirm.
        objects = list_objects(prefix="training/")
        logger.info("Objects in training/: %s", [o["key"] for o in objects])

        # Download back and verify.
        downloaded = download_training_data(key, dest_path=pathlib.Path(tmpdir) / "downloaded.csv")
        logger.info("Downloaded %d bytes", downloaded.stat().st_size)


# ---------------------------------------------------------------------------
# Step 4 — Celery: dispatch a training job
# ---------------------------------------------------------------------------

def step4_celery_training_job(training_data_key: str = "training/vehicle_features_2026-03-04.csv"):
    """Show how a Celery task would trigger model training.

    The actual Celery task is in backend/workers/tasks.py.
    Here we just show the dispatch call.
    """
    from backend.workers.tasks import run_ai_prediction

    logger.info("=== Step 4: Dispatch Celery training job ===")

    # In a training task the worker would:
    #   1. Download the training data from MinIO
    #   2. Train / fine-tune the model
    #   3. Upload the artefact back to MinIO
    #   4. Optionally push the new model version to Triton model repository

    # For demo purposes, dispatch the existing run_ai_prediction task.
    task = run_ai_prediction.delay(
        model_name="eta_model",
        input_data={
            "distance":      145.0,
            "traffic_score": 0.42,
            "vehicle_speed": 72.3,
        },
    )
    logger.info("Celery task dispatched: task_id=%s", task.id)
    return task.id


# ---------------------------------------------------------------------------
# Step 5 — Kafka: publish a route-optimization trigger
# ---------------------------------------------------------------------------

def step5_kafka_trigger(entity_id: str):
    """Show the Kafka → Feature Store → Triton → Kafka feedback loop."""
    from backend.streaming.kafka_producer import publish_event
    from kafka.errors import KafkaError

    logger.info("=== Step 5: Publish route-optimization trigger to Kafka ===")

    event = {
        "vehicle_id": entity_id,
        "reason":     "new_eta_available",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }

    try:
        publish_event("route-optimization-topic", event, key=entity_id)
        logger.info("Route optimization trigger published for %s", entity_id)
    except KafkaError as exc:
        logger.warning("Kafka unavailable (%s) — skipping trigger step", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting ML pipeline demonstration")

    # Step 1: Ingest features from a simulated Kafka event
    entity_id = step1_feature_ingestion()

    # Step 2: Predict ETA using Triton (gracefully skips if Triton is down)
    step2_eta_prediction(entity_id)

    # Step 3: Export training data to MinIO (gracefully skips if MinIO is down)
    step3_data_lake_export()

    # Step 4: Dispatch a Celery training job
    try:
        step4_celery_training_job()
    except Exception as exc:
        logger.warning("Celery dispatch skipped: %s", exc)

    # Step 5: Publish Kafka trigger for downstream consumers
    step5_kafka_trigger(entity_id)

    logger.info("ML pipeline demonstration complete")
