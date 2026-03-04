# =============================================================================
# backend/api/worker_routes.py
#
# FastAPI endpoints for enqueueing Celery background tasks and polling their
# status.  All endpoints return immediately — the heavy work happens in a
# separate Celery worker process.
#
# Routes
# ──────
# POST /jobs/optimize-route      →  enqueue optimize_routes task
# POST /jobs/run-prediction      →  enqueue run_ai_prediction task
# POST /jobs/run-simulation      →  enqueue long_running_job task
# GET  /jobs/task-status/{id}    →  poll task status & result
# =============================================================================

import logging
from typing import Any, Dict, List, Optional

from celery.result import AsyncResult
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from backend.workers.celery_app import celery_app
from backend.workers.tasks import long_running_job, optimize_routes, run_ai_prediction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Background Jobs"])


# =============================================================================
# Request / Response schemas
# =============================================================================

class OptimizeRouteRequest(BaseModel):
    warehouse_ids: List[int] = Field(
        ...,
        min_length=2,
        description="Ordered list of warehouse IDs to include in the route.",
        examples=[[1, 3, 7, 12]],
    )
    constraints: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional solver constraints, e.g. {'max_distance_km': 300}.",
    )


class RunPredictionRequest(BaseModel):
    features: Dict[str, Any] = Field(
        ...,
        description="Feature dict for the ML model.",
        examples=[{"warehouse_id": 3, "week_number": 12, "sku": "ABC-001"}],
    )
    model_name: str = Field(
        default="demand_forecast",
        description="Model identifier, e.g. 'demand_forecast', 'eta_model'.",
    )


class RunSimulationRequest(BaseModel):
    job_id: str = Field(
        ...,
        description="Caller-supplied idempotency key — re-submitting the same "
                    "job_id re-queues the task; use a UUID for uniqueness.",
        examples=["sim-2026-03-04-peak-season"],
    )
    config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Pipeline configuration, e.g. {'simulation_steps': 50, "
                    "'scenario': 'peak_season'}.",
    )


class TaskEnqueuedResponse(BaseModel):
    task_id: str = Field(..., description="Celery task ID — use this with /task-status.")
    status: str = Field(..., description="Always 'queued' on successful enqueue.")
    queue: str = Field(..., description="The Celery queue the task was routed to.")


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str = Field(
        ...,
        description="One of: PENDING, STARTED, PROGRESS, SUCCESS, FAILURE, REVOKED.",
    )
    result: Optional[Any] = Field(
        default=None,
        description="Task return value (SUCCESS) or error message (FAILURE).",
    )
    progress: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Intermediate progress info (percent, message) while PROGRESS.",
    )


# =============================================================================
# Helper: map Celery state to a client-friendly string
# =============================================================================

_STATE_MAP = {
    "PENDING":  "queued",
    "RECEIVED": "queued",
    "STARTED":  "running",
    "PROGRESS": "running",
    "SUCCESS":  "finished",
    "FAILURE":  "failed",
    "REVOKED":  "cancelled",
    "RETRY":    "retrying",
}


def _friendly_state(celery_state: str) -> str:
    return _STATE_MAP.get(celery_state, celery_state.lower())


# =============================================================================
# POST /jobs/optimize-route
# =============================================================================

@router.post(
    "/optimize-route",
    response_model=TaskEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a route-optimisation job",
    description=(
        "Enqueues an asynchronous route-optimisation task.  Returns immediately "
        "with a task_id.  Poll GET /jobs/task-status/{task_id} for the result."
    ),
)
def enqueue_optimize_route(payload: OptimizeRouteRequest) -> TaskEnqueuedResponse:
    task = optimize_routes.apply_async(
        args=[payload.warehouse_ids],
        kwargs={"constraints": payload.constraints},
    )
    logger.info(
        "optimize_route_enqueued",
        extra={"task_id": task.id, "warehouse_ids": payload.warehouse_ids},
    )
    return TaskEnqueuedResponse(
        task_id=task.id,
        status="queued",
        queue="optimization",
    )


# =============================================================================
# POST /jobs/run-prediction
# =============================================================================

@router.post(
    "/run-prediction",
    response_model=TaskEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue an AI prediction job",
    description=(
        "Enqueues an ML inference task.  Returns immediately with a task_id."
    ),
)
def enqueue_run_prediction(payload: RunPredictionRequest) -> TaskEnqueuedResponse:
    task = run_ai_prediction.apply_async(
        args=[payload.features],
        kwargs={"model_name": payload.model_name},
    )
    logger.info(
        "run_prediction_enqueued",
        extra={"task_id": task.id, "model_name": payload.model_name},
    )
    return TaskEnqueuedResponse(
        task_id=task.id,
        status="queued",
        queue="prediction",
    )


# =============================================================================
# POST /jobs/run-simulation
# =============================================================================

@router.post(
    "/run-simulation",
    response_model=TaskEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a long-running logistics simulation",
    description=(
        "Enqueues a multi-phase simulation or batch pipeline job.  "
        "Use the returned task_id to stream progress via /task-status."
    ),
)
def enqueue_run_simulation(payload: RunSimulationRequest) -> TaskEnqueuedResponse:
    task = long_running_job.apply_async(
        args=[payload.job_id],
        kwargs={"config": payload.config},
    )
    logger.info(
        "run_simulation_enqueued",
        extra={"task_id": task.id, "job_id": payload.job_id},
    )
    return TaskEnqueuedResponse(
        task_id=task.id,
        status="queued",
        queue="simulation",
    )


# =============================================================================
# GET /jobs/task-status/{task_id}
# =============================================================================

@router.get(
    "/task-status/{task_id}",
    response_model=TaskStatusResponse,
    summary="Poll task status and retrieve result",
    description=(
        "Returns the current state of any Celery task identified by task_id.  "
        "While the task is running the `progress` field contains `percent` "
        "and `message` from the worker."
    ),
)
def get_task_status(task_id: str) -> TaskStatusResponse:
    result: AsyncResult = AsyncResult(task_id, app=celery_app)
    state: str = result.state

    # FAILURE — the result is an Exception; serialise its message.
    if state == "FAILURE":
        exc = result.result
        return TaskStatusResponse(
            task_id=task_id,
            status="failed",
            result={"error": str(exc), "type": type(exc).__name__},
        )

    # PROGRESS — the task published an intermediate state.
    if state == "PROGRESS":
        meta = result.info or {}
        return TaskStatusResponse(
            task_id=task_id,
            status="running",
            progress=meta,
        )

    # SUCCESS — result is the task's return value.
    if state == "SUCCESS":
        return TaskStatusResponse(
            task_id=task_id,
            status="finished",
            result=result.result,
        )

    # PENDING / STARTED / RECEIVED / REVOKED / RETRY
    return TaskStatusResponse(
        task_id=task_id,
        status=_friendly_state(state),
    )
