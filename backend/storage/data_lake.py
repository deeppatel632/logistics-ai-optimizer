# backend/storage/data_lake.py
#
# ---------------------------------------------------------------------------
# Data Lake — MinIO Object Storage  (Step 50)
# ---------------------------------------------------------------------------
#
# MinIO is an S3-compatible object store used as the platform's data lake.
# All large binary assets are stored here rather than in SQL:
#
#   Bucket layout:
#   ─────────────
#   logistics-data-lake/
#   ├── training/          Raw & preprocessed training datasets (.csv, .parquet)
#   ├── models/            Trained model artefacts (.pkl, .onnx, .pt, .joblib)
#   ├── inference-logs/    Request/response logs for model monitoring
#   └── exports/           SQL export snapshots for offline analysis
#
# The boto3 S3 client is used because:
#   1. The same code runs against MinIO (dev), AWS S3 (prod), or Azure Blob
#      with the S3 compatibility API — no code changes required.
#   2. boto3 is already a transitive dependency of many ML libraries.
#   3. The MinIO-specific Python SDK (minio) is not necessary for these use
#      cases and avoids an extra dependency.
#
# Connection config (set via env vars / Settings):
#   MINIO_ENDPOINT       — http://minio:9000  (Docker) or S3 region URL
#   MINIO_ACCESS_KEY     — access key (MinIO root user or IAM key)
#   MINIO_SECRET_KEY     — secret (MinIO root password or IAM secret)
#   MINIO_BUCKET         — default bucket name (default: logistics-data-lake)
#   MINIO_USE_SSL        — true/false (false for local Docker, true for prod)
#
# ---------------------------------------------------------------------------

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Iterator

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from backend.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENDPOINT        = settings.minio_endpoint
_ACCESS_KEY      = settings.minio_access_key
_SECRET_KEY      = settings.minio_secret_key
_DEFAULT_BUCKET  = settings.minio_bucket
_USE_SSL         = settings.minio_use_ssl

# Standard prefix paths inside the default bucket
class Prefix:
    TRAINING        = "training/"
    MODELS          = "models/"
    INFERENCE_LOGS  = "inference-logs/"
    EXPORTS         = "exports/"


# ---------------------------------------------------------------------------
# S3 client singleton
# ---------------------------------------------------------------------------

_s3_client = None
_client_lock = threading.Lock()


def _get_s3_client():
    """Return (and lazily create) the shared boto3 S3 client for MinIO."""
    global _s3_client

    if _s3_client is not None:
        return _s3_client

    with _client_lock:
        if _s3_client is not None:
            return _s3_client

        logger.info(
            "minio_client_init",
            extra={"endpoint": _ENDPOINT, "bucket": _DEFAULT_BUCKET},
        )

        _s3_client = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
            use_ssl=_USE_SSL,
            # signature_version="s3v4" is required for MinIO
            config=Config(signature_version="s3v4"),
            # Suppress AWS region requirement — MinIO doesn't use regions.
            region_name="us-east-1",
        )

        logger.info("minio_client_ready")
        return _s3_client


# ---------------------------------------------------------------------------
# Bucket management
# ---------------------------------------------------------------------------

def create_bucket_if_missing(bucket: str = _DEFAULT_BUCKET) -> None:
    """Create the bucket if it does not already exist.

    Call once during application startup or Celery worker initialisation.
    Idempotent — safe to call repeatedly.

    Args:
        bucket: Bucket name.  Defaults to ``_DEFAULT_BUCKET``.
    """
    client = _get_s3_client()

    try:
        client.head_bucket(Bucket=bucket)
        logger.debug("minio_bucket_exists", extra={"bucket": bucket})
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
            logger.info("minio_bucket_created", extra={"bucket": bucket})
        else:
            # Re-raise unexpected errors (auth failure, etc.)
            raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upload_training_data(
    file_path: str | Path,
    object_name: str | None = None,
    bucket: str = _DEFAULT_BUCKET,
    prefix: str = Prefix.TRAINING,
) -> str:
    """Upload a local file to the data lake.

    Args:
        file_path:   Path to the local file to upload.
        object_name: Destination key inside the bucket.  If None, the file's
                     basename is used, prefixed with ``prefix``.
        bucket:      Target bucket (default: ``logistics-data-lake``).
        prefix:      Object key prefix (default: ``"training/"``).

    Returns:
        The full object key written to MinIO, e.g.
        ``"training/vehicle_features_2026-03-04.parquet"``.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        ClientError:       If the MinIO upload fails.

    Example::

        key = upload_training_data(
            "/tmp/features_export.parquet",
            object_name="vehicle_features_2026-03-04.parquet",
        )
        print(f"Uploaded to {key}")   # "training/vehicle_features_2026-03-04.parquet"

    Notes on the training data pipeline:
        Celery task (``export_training_data``) queries the ``ml_features``
        SQL table, serialises rows to Parquet, and calls this function.
        The resulting Parquet file is then read by the ML training job which
        loads it directly from MinIO using ``download_training_data``.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if object_name is None:
        object_name = prefix + file_path.name
    elif not object_name.startswith(prefix) and not object_name.startswith("/"):
        object_name = prefix + object_name

    client = _get_s3_client()

    # Ensure the bucket exists before uploading.
    create_bucket_if_missing(bucket)

    logger.info(
        "minio_upload_start",
        extra={
            "local_path": str(file_path),
            "bucket": bucket,
            "object_key": object_name,
        },
    )

    client.upload_file(
        Filename=str(file_path),
        Bucket=bucket,
        Key=object_name,
        # Multipart threshold: boto3 automatically splits files > 8 MB
        # (configurable via TransferConfig if needed).
    )

    logger.info(
        "minio_upload_complete",
        extra={
            "bucket": bucket,
            "object_key": object_name,
            "size_bytes": file_path.stat().st_size,
        },
    )

    return object_name


def download_training_data(
    object_name: str,
    dest_path: str | Path | None = None,
    bucket: str = _DEFAULT_BUCKET,
) -> Path:
    """Download an object from the data lake to a local file.

    Args:
        object_name: Object key, e.g. ``"training/vehicle_features.parquet"``.
                     If the key does not include a prefix it is used as-is.
        dest_path:   Local destination path.  If None, saves to ``/tmp/<basename>``.
        bucket:      Source bucket (default: ``logistics-data-lake``).

    Returns:
        Path to the downloaded local file.

    Raises:
        ClientError: If the object does not exist (404) or download fails.

    Example::

        local = download_training_data("training/vehicle_features.parquet")
        df = pd.read_parquet(local)
    """
    basename = Path(object_name).name
    dest_path = Path(dest_path) if dest_path else Path("/tmp") / basename

    # Create parent directories if needed.
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    client = _get_s3_client()

    logger.info(
        "minio_download_start",
        extra={"bucket": bucket, "object_key": object_name, "dest": str(dest_path)},
    )

    try:
        client.download_file(
            Bucket=bucket,
            Key=object_name,
            Filename=str(dest_path),
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("404", "NoSuchKey"):
            raise FileNotFoundError(
                f"Object '{object_name}' not found in bucket '{bucket}'"
            ) from exc
        raise

    logger.info(
        "minio_download_complete",
        extra={
            "bucket": bucket,
            "object_key": object_name,
            "dest": str(dest_path),
            "size_bytes": dest_path.stat().st_size,
        },
    )

    return dest_path


def upload_model_artefact(
    file_path: str | Path,
    model_name: str,
    version: str,
) -> str:
    """Upload a trained model artefact to ``models/<model_name>/<version>/``.

    Args:
        file_path:   Local path to the artefact file (.pkl, .onnx, etc.).
        model_name:  Model name, e.g.``"eta_model"``.
        version:     Version tag, e.g. ``"v1.2.0"`` or ``"20260304"``.

    Returns:
        Object key in MinIO.

    Example::

        key = upload_model_artefact("/tmp/eta_model.pkl", "eta_model", "v1.0.0")
        # "models/eta_model/v1.0.0/eta_model.pkl"
    """
    file_path = Path(file_path)
    object_name = f"{Prefix.MODELS}{model_name}/{version}/{file_path.name}"
    return upload_training_data(
        file_path=file_path,
        object_name=object_name,
        prefix="",   # object_name is already fully qualified
    )


def list_objects(
    prefix: str = "",
    bucket: str = _DEFAULT_BUCKET,
) -> list[dict]:
    """List objects in a bucket under the given prefix.

    Returns:
        List of dicts with keys: ``key``, ``size``, ``last_modified``.

    Example::

        training_files = list_objects(prefix="training/")
        for f in training_files:
            print(f["key"], f["size"])
    """
    client = _get_s3_client()

    paginator = client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    results = []
    for page in pages:
        for obj in page.get("Contents", []):
            results.append(
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                }
            )

    return results


def generate_presigned_url(
    object_name: str,
    expiry_seconds: int = 3600,
    bucket: str = _DEFAULT_BUCKET,
) -> str:
    """Generate a time-limited pre-signed download URL for an object.

    Useful for sharing training datasets or model artefacts with ML
    engineers without granting direct MinIO credentials.

    Args:
        object_name:     Object key.
        expiry_seconds:  URL lifetime in seconds (default: 1 hour).
        bucket:          Source bucket.

    Returns:
        Pre-signed HTTPS/HTTP URL string.
    """
    client = _get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_name},
        ExpiresIn=expiry_seconds,
    )
