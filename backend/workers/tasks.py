# =============================================================================
# backend/workers/tasks.py
#
# Celery background tasks for the logistics AI optimizer.
#
# Task categories
# ───────────────
# optimize_routes   →  queue: optimization  (CPU-bound route planning)
# run_ai_prediction →  queue: prediction    (ML model inference)
# long_running_job  →  queue: simulation    (data pipeline / simulation)
#
# All tasks share the same design contract:
#   • bind=True         — first arg is `self` (the task instance), enables
#                         retry() and custom state updates via self.update_state().
#   • autoretry_for     — automatically retry on transient errors.
#   • retry_backoff     — exponential back-off (1 s, 2 s, 4 s, …) so a flaky
#                         downstream service is not hammered.
#   • retry_jitter      — adds random ± jitter to back-off to prevent the
#                         "thundering herd" when many tasks retry at once.
#   • max_retries=3     — give up after three attempts and transition to FAILURE.
#   • SoftTimeLimitExceeded is caught so each task can release resources
#     (close DB sessions, flush buffers) before the hard SIGKILL arrives.
# =============================================================================

import logging
import random
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from backend.workers.celery_app import celery_app
from database.connection import SessionLocal

# Use Celery's task-aware logger — log records are decorated with
# task_id and task_name automatically.
logger: logging.Logger = get_task_logger(__name__)


# =============================================================================
# Database session context manager
# Each task that needs DB access creates its own short-lived session.
# Using a context manager ensures the session is always closed even when
# the task raises an exception.
# =============================================================================

@contextmanager
def task_db_session():
    """Yield a SQLAlchemy session and guarantee cleanup.

    Usage::

        with task_db_session() as db:
            warehouse = db.query(Warehouse).filter_by(id=wh_id).first()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# =============================================================================
# Task 1 — optimize_routes
#
# Accepts a list of warehouse / delivery stop IDs and optional constraints,
# returns an ordered list representing the optimised traversal order.
#
# Production implementation note:
#   Replace the stub body with a call to your routing engine (OR-Tools VRP
#   solver, Google Maps Routes API, custom ML model, etc.).  The Celery
#   scaffolding (retry, timeout handling, state updates) stays identical.
# =============================================================================

@celery_app.task(
    bind=True,
    name="backend.workers.tasks.optimize_routes",
    max_retries=3,
    # Retry on any exception; exponential back-off with jitter.
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,   # cap back-off at 2 minutes
    retry_jitter=True,
    # Override the global soft/hard limits for this specific task.
    soft_time_limit=180,
    time_limit=240,
)
def optimize_routes(
    self: Task,
    warehouse_ids: List[int],
    constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Optimise delivery routes between a set of warehouses.

    Args:
        warehouse_ids: Ordered list of warehouse IDs to include in the route.
        constraints:   Optional dict of constraints, e.g.:
                       {"max_distance_km": 500, "vehicle_type": "truck"}

    Returns:
        Dict with keys:
            optimized_route  — reordered warehouse IDs
            total_distance   — estimated distance in km
            estimated_hours  — estimated travel time
            algorithm        — name of the solver used
    """
    logger.info(
        "optimize_routes_started",
        extra={"warehouse_ids": warehouse_ids, "constraints": constraints},
    )

    try:
        # ------------------------------------------------------------------
        # Progress update — clients polling /task-status/{task_id} will see
        # "running" and a percentage instead of just "PENDING".
        # ------------------------------------------------------------------
        self.update_state(
            state="PROGRESS",
            meta={"percent": 0, "message": "loading warehouse coordinates"},
        )

        with task_db_session() as db:
            # ----------------------------------------------------------------
            # ↳ Replace with real DB query + route solver.
            # Example real implementation:
            #
            #   from database.models import Warehouse
            #   warehouses = (
            #       db.query(Warehouse)
            #       .filter(Warehouse.id.in_(warehouse_ids))
            #       .all()
            #   )
            #   coords = [(w.latitude, w.longitude) for w in warehouses]
            #   optimized_ids = vrp_solver.solve(coords, constraints)
            # ----------------------------------------------------------------
            _ = db  # session available but not used in the stub

        self.update_state(
            state="PROGRESS",
            meta={"percent": 40, "message": "running optimisation solver"},
        )

        # --- Stub: nearest-neighbour heuristic on random distances ----------
        n = len(warehouse_ids)
        if n == 0:
            raise ValueError("warehouse_ids must not be empty")

        rng = random.Random(sum(warehouse_ids))   # deterministic for repeatability
        distance_matrix = [
            [rng.uniform(10, 500) if i != j else 0.0 for j in range(n)]
            for i in range(n)
        ]

        unvisited = list(range(n))
        order = [unvisited.pop(0)]
        while unvisited:
            last = order[-1]
            nearest = min(unvisited, key=lambda x: distance_matrix[last][x])
            order.append(nearest)
            unvisited.remove(nearest)

        optimized_route = [warehouse_ids[i] for i in order]
        total_distance = sum(
            distance_matrix[order[i]][order[i + 1]] for i in range(len(order) - 1)
        )
        # Assume 60 km/h average speed
        estimated_hours = round(total_distance / 60.0, 2)
        # ---------------------------------------------------------------------

        self.update_state(
            state="PROGRESS",
            meta={"percent": 90, "message": "finalising result"},
        )

        result = {
            "optimized_route": optimized_route,
            "total_distance": round(total_distance, 2),
            "estimated_hours": estimated_hours,
            "algorithm": "nearest_neighbour_stub",
            "constraints_applied": constraints or {},
        }

        logger.info(
            "optimize_routes_completed",
            extra={"optimized_route": optimized_route, "total_distance": total_distance},
        )
        return result

    except SoftTimeLimitExceeded:
        # Soft timeout: do cleanup before the hard SIGKILL fires.
        logger.warning("optimize_routes_soft_timeout_exceeded")
        raise


# =============================================================================
# Task 2 — run_ai_prediction
#
# Runs an ML inference pass for a named model and a feature vector.
#
# Production implementation note:
#   - Load model from backend/ml_engine/models/ using joblib / pickle.
#   - Cache the loaded model in a module-level dict (not reloaded each call).
#   - For GPU inference, pin the task to a GPU-worker queue in task_routes.
# =============================================================================

@celery_app.task(
    bind=True,
    name="backend.workers.tasks.run_ai_prediction",
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    soft_time_limit=120,
    time_limit=180,
)
def run_ai_prediction(
    self: Task,
    features: Dict[str, Any],
    model_name: str = "demand_forecast",
) -> Dict[str, Any]:
    """Run AI model inference for a logistics prediction use case.

    Args:
        features:   Feature dict passed to the model, e.g.:
                    {"warehouse_id": 3, "week_number": 12, "sku": "ABC-001"}
        model_name: Which model to load, e.g. "demand_forecast", "eta_model",
                    "dispatch_model".

    Returns:
        Dict with keys:
            model_name   — model that generated the prediction
            prediction   — scalar or dict output from the model
            confidence   — float [0, 1]
            features_in  — echo of the input features
    """
    logger.info(
        "run_ai_prediction_started",
        extra={"model_name": model_name, "features": features},
    )

    try:
        self.update_state(
            state="PROGRESS",
            meta={"percent": 10, "message": f"loading model: {model_name}"},
        )

        # ------------------------------------------------------------------
        # ↳ Replace with real model loading + inference.
        # Example real implementation:
        #
        #   import joblib, os
        #   _MODEL_CACHE: Dict[str, Any] = {}
        #   model_path = f"ml_engine/models/{model_name}.pkl"
        #   if model_name not in _MODEL_CACHE:
        #       _MODEL_CACHE[model_name] = joblib.load(model_path)
        #   model = _MODEL_CACHE[model_name]
        #   feature_array = np.array([list(features.values())])
        #   prediction = float(model.predict(feature_array)[0])
        # ------------------------------------------------------------------

        # Stub: deterministic fake prediction
        seed = hash(str(sorted(features.items()))) % (2 ** 31)
        rng = random.Random(seed)
        prediction = round(rng.uniform(10.0, 1000.0), 2)
        confidence = round(rng.uniform(0.70, 0.99), 4)

        self.update_state(
            state="PROGRESS",
            meta={"percent": 90, "message": "inference complete"},
        )

        result = {
            "model_name": model_name,
            "prediction": prediction,
            "confidence": confidence,
            "features_in": features,
        }

        logger.info(
            "run_ai_prediction_completed",
            extra={"model_name": model_name, "prediction": prediction},
        )
        return result

    except SoftTimeLimitExceeded:
        logger.warning("run_ai_prediction_soft_timeout", extra={"model_name": model_name})
        raise


# =============================================================================
# Task 3 — long_running_job
#
# Handles arbitrary long-running logistics simulations or batch pipelines.
# Reports granular progress so the caller can display a progress bar.
#
# Production implementation note:
#   - Segment the job into phases and call self.update_state() at each phase.
#   - Store partial results in Redis / DB so the job can be resumed if
#     interrupted (idempotency via the job_id key).
# =============================================================================

@celery_app.task(
    bind=True,
    name="backend.workers.tasks.long_running_job",
    max_retries=2,          # Fewer retries — expensive jobs should not loop.
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    # Long-running jobs get a generous timeout.
    soft_time_limit=210,
    time_limit=240,
)
def long_running_job(
    self: Task,
    job_id: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a multi-phase logistics simulation or batch data pipeline.

    Args:
        job_id:  Caller-supplied idempotency key (store results under this key).
        config:  Arbitrary configuration dict for the pipeline:
                 {"simulation_steps": 100, "scenario": "peak_season"}

    Returns:
        Dict with keys:
            job_id           — echoed back for correlation
            phases_completed — list of completed phase names
            summary          — high-level outcome metrics
    """
    cfg = config or {}
    steps = int(cfg.get("simulation_steps", 10))
    scenario = str(cfg.get("scenario", "default"))

    logger.info(
        "long_running_job_started",
        extra={"job_id": job_id, "steps": steps, "scenario": scenario},
    )

    phases_completed: List[str] = []

    # Phase definitions: (name, weight_pct)  — weights must sum to 100
    phases = [
        ("data_ingestion", 20),
        ("preprocessing", 20),
        ("simulation_run", 40),
        ("result_aggregation", 15),
        ("report_generation", 5),
    ]
    cumulative = 0

    try:
        for phase_name, weight in phases:
            self.update_state(
                state="PROGRESS",
                meta={
                    "percent": cumulative,
                    "message": f"running phase: {phase_name}",
                    "phases_completed": phases_completed,
                },
            )

            # ------------------------------------------------------------------
            # ↳ Replace each stub with real phase logic.
            # ------------------------------------------------------------------
            if phase_name == "data_ingestion":
                with task_db_session() as db:
                    _ = db   # placeholder for real DB reads
                    time.sleep(0.05 * steps)

            elif phase_name == "simulation_run":
                # Simulate step-by-step with per-step progress updates.
                for step in range(steps):
                    if step % max(1, steps // 10) == 0:
                        self.update_state(
                            state="PROGRESS",
                            meta={
                                "percent": cumulative + weight * step // steps,
                                "message": f"simulation step {step}/{steps}",
                                "phases_completed": phases_completed,
                            },
                        )
                    time.sleep(0.01)  # replace with real simulation tick
            else:
                time.sleep(0.02)  # placeholder for other phases

            phases_completed.append(phase_name)
            cumulative += weight

        result = {
            "job_id": job_id,
            "phases_completed": phases_completed,
            "summary": {
                "scenario": scenario,
                "steps_simulated": steps,
                "status": "completed",
            },
        }

        logger.info(
            "long_running_job_completed",
            extra={"job_id": job_id, "phases": phases_completed},
        )
        return result

    except SoftTimeLimitExceeded:
        # Graceful degradation: return partial results rather than failing hard.
        logger.warning(
            "long_running_job_soft_timeout",
            extra={"job_id": job_id, "completed_phases": phases_completed},
        )
        raise
