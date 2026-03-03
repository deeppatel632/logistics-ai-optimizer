from fastapi import APIRouter
from database.connection import engine
from sqlalchemy import text
from backend.core.queue import redis_conn

router = APIRouter()


@router.get("/health/live")
def liveness_check():
    """
    Basic process check.
    If this returns, app is alive.
    """
    return {"status": "alive"}


@router.get("/health/ready")
def readiness_check():
    """
    Checks DB and Redis connectivity.
    """

    # Check DB
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return {"status": "not ready", "database": "down"}

    # Check Redis
    try:
        redis_conn.ping()
    except Exception:
        return {"status": "not ready", "redis": "down"}

    return {"status": "ready"}