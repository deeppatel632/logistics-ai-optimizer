# =============================================================================
# backend/workers/celery_app.py
#
# Central Celery application instance for the logistics AI optimizer.
#
# Architecture:
#   FastAPI  →  .apply_async()  →  Redis broker  →  Celery workers
#                                                       ↓
#                                               backend.workers.tasks.*
#
# Queue topology (one queue per workload type lets you scale each pool
# of workers independently):
#
#   Queue          Tasks routed here         Scale guidance
#   ──────────────────────────────────────────────────────
#   celery         default / misc             1-2 workers
#   optimization   optimize_routes            CPU-bound: 1 worker per core
#   prediction     run_ai_prediction          GPU/CPU-bound: tie to ML infra
#   simulation     long_running_job           memory-bound: 1-2 workers
#
# To consume specific queues on start (per docker-compose service):
#   celery -A backend.workers.celery_app worker -Q optimization,celery -c 4
# =============================================================================

import logging

from celery import Celery
from celery.signals import worker_ready, worker_shutdown, task_prerun, task_postrun
from kombu import Exchange, Queue

from backend.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Broker and result-backend URLs built from pydantic Settings.
# No hardcoded URLs here — all values come from environment variables.
# Both broker and backend point at the same Redis instance; use separate
# Redis DBs if you need isolation (e.g. broker=redis://.../0, backend=.../1).
# ---------------------------------------------------------------------------
_redis_url = (
    f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
)

# ---------------------------------------------------------------------------
# Celery application instance.
#
# `include` performs *explicit* task discovery at startup so workers know
# about all tasks without scanning the entire package tree.
# If you add a new task module, append it here.
# ---------------------------------------------------------------------------
celery_app = Celery(
    # Application name — used as a prefix in Redis keys and Flower.
    "logistics_optimizer",
    broker=_redis_url,
    backend=_redis_url,
    include=["backend.workers.tasks"],
)

# =============================================================================
# Configuration
# All options documented inline.  For a full reference see:
# https://docs.celeryq.dev/en/stable/userguide/configuration.html
# =============================================================================
celery_app.conf.update(

    # -------------------------------------------------------------------------
    # Serialization
    # JSON is the only accepted format — never pickle (security risk).
    # -------------------------------------------------------------------------
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # -------------------------------------------------------------------------
    # Time zone
    # -------------------------------------------------------------------------
    timezone="UTC",
    enable_utc=True,

    # -------------------------------------------------------------------------
    # Task execution semantics
    #
    # task_track_started=True
    #   The task state transitions to STARTED when a worker picks it up.
    #   Without this, tasks jump directly from PENDING to SUCCESS/FAILURE,
    #   making /task-status/{task_id} useless for long-running jobs.
    #
    # task_acks_late=True
    #   ACK is sent to the broker *after* the task completes (not on receipt).
    #   If a worker crashes mid-execution the task is re-queued automatically.
    #   Requires tasks to be idempotent (re-running them must be safe).
    #
    # task_reject_on_worker_lost=True
    #   Complement to acks_late: explicitly re-queue (not discard) tasks when
    #   the worker process is killed (SIGKILL, OOM, container restart).
    #
    # worker_prefetch_multiplier=1
    #   Disable Celery's aggressive prefetch.  Each worker process fetches
    #   exactly one task at a time.  Critical when tasks have wildly varying
    #   execution times; prevents a slow task from blocking fast ones.
    # -------------------------------------------------------------------------
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,

    # -------------------------------------------------------------------------
    # Timeouts
    #
    # task_soft_time_limit   Raises SoftTimeLimitExceeded inside the task.
    #                        The task can catch it to do cleanup before dying.
    # task_time_limit        Hard kill (SIGKILL) if the soft limit is ignored.
    #                        Set higher than soft_time_limit.
    # -------------------------------------------------------------------------
    task_soft_time_limit=240,   # 4 minutes — catchable
    task_time_limit=300,        # 5 minutes — hard kill

    # -------------------------------------------------------------------------
    # Result backend
    # Results are stored in Redis and expire automatically.
    # task_ignore_result=False must remain False for /task-status to work.
    # -------------------------------------------------------------------------
    result_expires=3600,        # Expire results after 1 hour
    task_ignore_result=False,

    # -------------------------------------------------------------------------
    # Queue routing
    # One exchange + queue per workload type.  This lets you run separate
    # worker pools (e.g. GPU workers on `prediction`, multi-core workers on
    # `optimization`) without any worker receiving the wrong task type.
    # -------------------------------------------------------------------------
    task_default_queue="celery",
    task_queues=(
        Queue("celery",       Exchange("celery"),       routing_key="celery"),
        Queue("optimization", Exchange("optimization"), routing_key="optimization"),
        Queue("prediction",   Exchange("prediction"),   routing_key="prediction"),
        Queue("simulation",   Exchange("simulation"),   routing_key="simulation"),
    ),
    task_routes={
        "backend.workers.tasks.optimize_routes":   {"queue": "optimization"},
        "backend.workers.tasks.run_ai_prediction": {"queue": "prediction"},
        "backend.workers.tasks.long_running_job":  {"queue": "simulation"},
    },

    # -------------------------------------------------------------------------
    # Monitoring (Flower)
    # worker_send_task_events and task_send_sent_event expose real-time task
    # state to Flower's event stream.  Safe to disable in cost-sensitive envs.
    # -------------------------------------------------------------------------
    worker_send_task_events=True,
    task_send_sent_event=True,
)


# =============================================================================
# Worker lifecycle signals — structured log entries visible in JSON log stream
# =============================================================================

@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    logger.info("celery_worker_ready", extra={"hostname": sender.hostname})


@worker_shutdown.connect
def on_worker_shutdown(sender, **kwargs):
    logger.info("celery_worker_shutdown", extra={"hostname": sender.hostname})


@task_prerun.connect
def on_task_prerun(task_id, task, args, kwargs, **_):
    logger.info(
        "task_started",
        extra={"task_id": task_id, "task_name": task.name},
    )


@task_postrun.connect
def on_task_postrun(task_id, task, retval, state, **_):
    logger.info(
        "task_finished",
        extra={"task_id": task_id, "task_name": task.name, "state": state},
    )
