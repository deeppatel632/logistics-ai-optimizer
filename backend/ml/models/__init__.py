# backend/ml/models/__init__.py
#
# Model serving sub-package.
#
# Provides a clean interface between the FastAPI / Celery layer and the
# NVIDIA Triton Inference Server.
#
#   model_client.py     — low-level HTTP transport to Triton (retry, timeout)
#   inference_service.py — domain-level functions (predict_eta, etc.) that
#                          compose the feature store + model client

from backend.ml.models.inference_service import (
    predict_eta,
    predict_demand,
    batch_predict_eta,
)

__all__ = ["predict_eta", "predict_demand", "batch_predict_eta"]
