# backend/main.py

import logging
import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from backend.core.rate_limiter import limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler
from backend.api import audit_routes, auth_routes, health_routes, streaming_routes, warehouse_routes, worker_routes
from backend.streaming.kafka_producer import close_producer
from backend.core.logging_config import configure_logging
from backend.core.metrics import REQUEST_COUNT, REQUEST_LATENCY
from backend.core.tenant_middleware import TenantMiddleware
from backend.core.tracing import configure_tracing
from database.connection import engine, validate_database_connection
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

configure_logging()
configure_tracing()

logger = logging.getLogger(__name__)


# ---------------------------------------------------
# App
# ---------------------------------------------------

app = FastAPI(
    title="Global Logistics & Supply Chain Optimizer",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"},
    ),
)
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(TenantMiddleware)

FastAPIInstrumentor.instrument_app(app)

# ---------------------------------------------------
# Routers
# ---------------------------------------------------

app.include_router(health_routes.router)
app.include_router(auth_routes.router)
app.include_router(warehouse_routes.router)
app.include_router(audit_routes.router)
app.include_router(worker_routes.router)
app.include_router(streaming_routes.router)


# ---------------------------------------------------
# Startup
# ---------------------------------------------------

@app.on_event("startup")
def startup_event() -> None:
    validate_database_connection(engine)
    logger.info("application_started")


@app.on_event("shutdown")
def shutdown_event() -> None:
    # Flush any buffered Kafka messages before the process exits.
    close_producer()
    logger.info("application_stopped")


# ---------------------------------------------------
# Request context middleware
# ---------------------------------------------------

@app.middleware("http")
async def request_context_middleware(request: Request, call_next: Callable) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    start = time.time()
    response = await call_next(request)
    duration = time.time() - start

    path = request.url.path

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=path,
        http_status=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(endpoint=path).observe(duration)

    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": path,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
        },
    )

    return response


# ---------------------------------------------------
# Metrics
# ---------------------------------------------------

@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
