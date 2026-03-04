# backend/ml/models/model_client.py
#
# ---------------------------------------------------------------------------
# Triton Inference Server HTTP Client  (Step 49)
# ---------------------------------------------------------------------------
#
# NVIDIA Triton Inference Server exposes a standard HTTP REST API defined by
# the KServe Inference Protocol v2:
#   https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/protocol/extension_http.html
#
# Request format (v2 infer):
#
#   POST /v2/models/<model_name>/infer
#   {
#     "inputs": [
#       {"name": "INPUT0", "shape": [batch_size, n_features],
#        "datatype": "FP32", "data": [[...], [...]]}
#     ],
#     "outputs": [{"name": "OUTPUT0"}]
#   }
#
# This module provides a low-level client that:
#   • Manages a single httpx.Client (connection pool, keep-alive)
#   • Serialises / deserialises the v2 request/response envelope
#   • Retries transient failures with exponential back-off
#   • Raises typed exceptions so callers can present meaningful HTTP errors
#
# ---------------------------------------------------------------------------

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from backend.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Triton's base URL is configured via Settings.
_TRITON_BASE_URL: str = settings.triton_base_url

# HTTP timeouts (seconds)
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 30.0     # generous; large batch inference can take ~20 s

# Retry policy
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 0.5   # seconds;  sleep = base * 2^attempt

# Triton KServe v2 inference endpoint template
_INFER_URL_TEMPLATE = "{base}/v2/models/{model}/infer"
_HEALTH_URL_TEMPLATE = "{base}/v2/health/ready"
_MODEL_META_URL_TEMPLATE = "{base}/v2/models/{model}"

# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------

class TritonClientError(Exception):
    """Base class for all Triton client errors."""


class TritonUnavailableError(TritonClientError):
    """Raised when the Triton server is unreachable or returns 5xx."""


class TritonModelNotFoundError(TritonClientError):
    """Raised when the requested model does not exist on the server."""


class TritonInferenceError(TritonClientError):
    """Raised when Triton returns a 4xx error for an inference request."""


# ---------------------------------------------------------------------------
# Internal HTTP client (shared across all callers)
# ---------------------------------------------------------------------------

_http_client: httpx.Client | None = None


def _get_http_client() -> httpx.Client:
    """Return the shared httpx.Client, creating it on first call."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(
            base_url=_TRITON_BASE_URL,
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT,
                read=_READ_TIMEOUT,
                write=10.0,
                pool=5.0,
            ),
            headers={"Content-Type": "application/json"},
            # httpx connection pool — reuse TCP connections across requests.
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        logger.info(
            "triton_client_created",
            extra={"base_url": _TRITON_BASE_URL},
        )
    return _http_client


def close_http_client() -> None:
    """Close the shared HTTP client.  Call during application shutdown."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        _http_client.close()
        _http_client = None
        logger.info("triton_client_closed")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def triton_health_check() -> bool:
    """Return True if Triton is ready to serve requests."""
    try:
        resp = _get_http_client().get(
            _HEALTH_URL_TEMPLATE.format(base=""),   # base_url already set
        )
        return resp.status_code == 200
    except httpx.TransportError:
        return False


def infer(
    model_name: str,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]] | None = None,
    model_version: str = "",
) -> dict[str, Any]:
    """Send an inference request to a Triton model and return the raw response.

    Args:
        model_name:    Triton model repository name, e.g. ``"eta_model"``.
        inputs:        List of KServe v2 ``inputs`` dicts.
        outputs:       Optional list of requested output tensors.  If None,
                       Triton returns all model outputs.
        model_version: Optional model version string.  Empty string means
                       "latest" (Triton default).

    Returns:
        Parsed JSON response from Triton containing ``outputs`` with
        inference results.

    Raises:
        TritonUnavailableError:    Server unreachable or 5xx.
        TritonModelNotFoundError:  Model not loaded on the server (404).
        TritonInferenceError:      Bad request / malformed input (4xx).

    Notes:
        The request body follows the KServe Inference Protocol v2::

            {
              "inputs": [
                {
                  "name": "INPUT0",
                  "shape": [1, 3],
                  "datatype": "FP32",
                  "data": [[120.5, 0.65, 70.0]]
                }
              ],
              "outputs": [{"name": "OUTPUT0"}]
            }
    """
    version_segment = f"/versions/{model_version}" if model_version else ""
    url = f"/v2/models/{model_name}{version_segment}/infer"

    payload: dict[str, Any] = {"inputs": inputs}
    if outputs:
        payload["outputs"] = outputs

    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            resp = _get_http_client().post(url, json=payload)

            if resp.status_code == 200:
                logger.debug(
                    "triton_infer_success",
                    extra={"model": model_name, "attempt": attempt + 1},
                )
                return resp.json()

            if resp.status_code == 404:
                raise TritonModelNotFoundError(
                    f"Model '{model_name}' not found on Triton: {resp.text}"
                )

            if 400 <= resp.status_code < 500:
                raise TritonInferenceError(
                    f"Triton returned {resp.status_code} for model '{model_name}': "
                    f"{resp.text}"
                )

            # 5xx — server error, retry
            logger.warning(
                "triton_server_error",
                extra={
                    "model": model_name,
                    "status_code": resp.status_code,
                    "attempt": attempt + 1,
                    "body": resp.text[:200],
                },
            )
            last_exc = TritonUnavailableError(
                f"Triton returned {resp.status_code}: {resp.text[:200]}"
            )

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.warning(
                "triton_connection_error",
                extra={"model": model_name, "attempt": attempt + 1, "error": str(exc)},
            )
            last_exc = TritonUnavailableError(f"Triton connection failed: {exc}")

        # Exponential back-off before the next attempt.
        if attempt < _MAX_RETRIES - 1:
            backoff = _RETRY_BACKOFF_BASE * (2 ** attempt)
            logger.info(
                "triton_retry_backoff",
                extra={
                    "model": model_name,
                    "attempt": attempt + 1,
                    "backoff_seconds": backoff,
                },
            )
            time.sleep(backoff)

    raise last_exc or TritonUnavailableError("Triton infer failed after all retries")


def get_model_metadata(model_name: str) -> dict[str, Any]:
    """Return Triton model metadata (input/output tensor specs)."""
    url = f"/v2/models/{model_name}"
    try:
        resp = _get_http_client().get(url)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            raise TritonModelNotFoundError(f"Model '{model_name}' not found")
        raise TritonUnavailableError(f"Triton returned {resp.status_code}")
    except httpx.TransportError as exc:
        raise TritonUnavailableError(f"Triton unreachable: {exc}") from exc


# ---------------------------------------------------------------------------
# Low-level tensor builder helpers
# ---------------------------------------------------------------------------

def build_fp32_input(
    name: str,
    data: list[list[float]],
) -> dict[str, Any]:
    """Build a KServe v2 FP32 input tensor dict.

    Args:
        name:  tensor name matching the model's config.pbtxt
        data:  2-D list [[row0_feat0, row0_feat1, ...], [row1_feat0, ...]]
               shape is inferred as [n_rows, n_features].

    Example::

        inp = build_fp32_input("INPUT0", [[120.5, 0.65, 70.0]])
        # {"name": "INPUT0", "shape": [1, 3], "datatype": "FP32",
        #  "data": [[120.5, 0.65, 70.0]]}
    """
    n_rows = len(data)
    n_cols = len(data[0]) if data else 0
    return {
        "name": name,
        "shape": [n_rows, n_cols],
        "datatype": "FP32",
        "data": data,
    }


def extract_fp32_output(
    response: dict[str, Any],
    output_name: str = "OUTPUT0",
) -> list[list[float]]:
    """Extract a 2-D FP32 output tensor from a Triton response.

    Returns:
        2-D list mirroring the output tensor shape.

    Raises:
        KeyError: If ``output_name`` is not present in the response.
    """
    for out in response.get("outputs", []):
        if out["name"] == output_name:
            return out["data"]
    raise KeyError(
        f"Output '{output_name}' not found in Triton response. "
        f"Available outputs: {[o['name'] for o in response.get('outputs', [])]}"
    )
