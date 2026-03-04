# backend/storage/__init__.py
#
# Object storage / data lake layer — backed by MinIO (S3-compatible API).
#
# MinIO is used as the platform's data lake for:
#   • Raw training datasets exported from operational SQL tables
#   • Pre-processed feature matrices (numpy .npy, parquet)
#   • Trained model artefacts (.pkl, .onnx, .pt)
#   • Inference logs for model monitoring / drift detection
#
# The boto3 S3 client is used instead of the MinIO-specific SDK so the same
# code works unchanged against AWS S3, Azure Blob (via S3 compatibility
# layer), or any other S3-compatible store.

from backend.storage.data_lake import (
    upload_training_data,
    download_training_data,
    list_objects,
    create_bucket_if_missing,
)

__all__ = [
    "upload_training_data",
    "download_training_data",
    "list_objects",
    "create_bucket_if_missing",
]
