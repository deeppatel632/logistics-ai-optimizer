import pybreaker
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from database.connection import safe_db_check
from backend.core.queue import redis_conn

router = APIRouter()


@router.get("/health/live")
def liveness_check():
    return {"status": "alive"}


@router.get("/health/ready")
def readiness_check():
    try:
        safe_db_check()
    except pybreaker.CircuitBreakerError:
        return JSONResponse(status_code=503, content={"status": "not ready", "detail": "circuit open"})
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not ready", "detail": "database unavailable"})

    try:
        redis_conn.ping()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not ready", "detail": "redis unavailable"})

    return {"status": "ready"}