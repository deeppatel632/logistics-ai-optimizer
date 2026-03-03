from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend.core.logger import logger
from backend.api import warehouse_routes, auth_routes, health_routes
from database.connection import engine, validate_database_connection
from database.models import Base
import uuid
import time
from backend.core.limiter import limiter
from backend.core.metrics import REQUEST_COUNT, REQUEST_LATENCY, ERROR_COUNT
from prometheus_client import generate_latest
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ---------------------------------------------------
# Create FastAPI App
# ---------------------------------------------------

app = FastAPI(
    title="Global Logistics & Supply Chain Optimizer",
    version="1.0.0"
)
app.include_router(health_routes.router)
app.include_router(warehouse_routes.router)
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
async def request_logging_middleware(request: Request, call_next):

    request_id = str(uuid.uuid4())
    start_time = time.time()
    method = request.method
    endpoint = request.url.path

    logger.info(f"[{request_id}] Incoming request: {method} {endpoint}")

    try:
        response = await call_next(request)

        duration = time.time() - start_time

        REQUEST_COUNT.labels(
            method=method,
            endpoint=endpoint,
            status=response.status_code
        ).inc()

        REQUEST_LATENCY.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)

        logger.info(
            f"[{request_id}] Completed in {round(duration * 1000, 2)}ms "
            f"| Status {response.status_code}"
        )

        return response

    except Exception as e:
        ERROR_COUNT.inc()
        logger.error(f"[{request_id}] Request failed: {str(e)}")
        raise

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