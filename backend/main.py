from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend.core.logger import logger
from backend.api import warehouse_routes
from database.connection import engine, validate_database_connection
from database.models import Base
import uuid
from backend.api import health_routes
import time


# ---------------------------------------------------
# Create FastAPI App
# ---------------------------------------------------

app = FastAPI(
    title="Global Logistics & Supply Chain Optimizer",
    version="1.0.0"
)
app.include_router(health_routes.router)

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

    logger.info(
        f"[{request_id}] Incoming request: "
        f"{request.method} {request.url.path}"
    )

    try:
        response = await call_next(request)

        duration = round((time.time() - start_time) * 1000, 2)

        logger.info(
            f"[{request_id}] Completed in {duration}ms "
            f"| Status {response.status_code}"
        )

        return response

    except Exception as e:
        logger.error(
            f"[{request_id}] Request failed: {str(e)}"
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )


# ---------------------------------------------------
# Include Routers
# ---------------------------------------------------

app.include_router(warehouse_routes.router)