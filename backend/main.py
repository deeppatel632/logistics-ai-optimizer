from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend.core.logger import logger
from backend.api import warehouse_routes, auth_routes, health_routes
from database.connection import engine, validate_database_connection
from database.models import Base
import uuid
import time
from backend.core.tenant_middleware import TenantMiddleware
from backend.core.limiter import limiter
from backend.core.metrics import REQUEST_COUNT, REQUEST_LATENCY, ERROR_COUNT
from prometheus_client import generate_latest
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from backend.api import audit_routes
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

# ---------------------------------------------------
# Create FastAPI App
# ---------------------------------------------------

app = FastAPI(
    title="Global Logistics & Supply Chain Optimizer",
    version="1.0.0"
)
app.include_router(health_routes.router)
app.include_router(warehouse_routes.router)
app.include_router(audit_routes.router)
app.add_middleware(TenantMiddleware)
app.include_router(auth_routes.router)
app.state.limiter = limiter
# ---------------------------------------------------
# Rate Limiting Middleware
# ---------------------------------------------------

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"]
)

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"},
    ),
)

# ---------------------------------------------------
# Startup Event (DB Validation Only)
# ---------------------------------------------------

@app.on_event("startup")
def startup_event():
    """
    Runs when application starts.
    Validates DB connection.
    """

    logger.info("Starting application...")

    validate_database_connection(engine)

    logger.info("Application startup complete.")


# ---------------------------------------------------
# Request Logging Middleware
# ---------------------------------------------------
@app.middleware("http")
async def metrics_middleware(request, call_next):
    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time

    endpoint = request.url.path

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        http_status=response.status_code
    ).inc()

    REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration)

    return response

# ---------------------------------------------------
# Metrics Endpoint
# ---------------------------------------------------
@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

# ---------------------------------------------------
# Include Routers
# ---------------------------------------------------

app.include_router(warehouse_routes.router)

@app.get("/health/live")
def liveness():
    return {"status": "alive"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)