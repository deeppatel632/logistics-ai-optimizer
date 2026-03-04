# tests/test_api.py
#
# Health-endpoint integration tests.
# All database and Redis calls are mocked so these run with no real
# infrastructure (safe for CI).

from unittest.mock import MagicMock, patch

import pybreaker
import pytest


# ---------------------------------------------------------------------------
# /health/live
# ---------------------------------------------------------------------------

class TestLiveness:
    def test_returns_200(self, client):
        response = client.get("/health/live")
        assert response.status_code == 200

    def test_body_contains_alive(self, client):
        response = client.get("/health/live")
        assert response.json() == {"status": "alive"}


# ---------------------------------------------------------------------------
# /health/ready
# ---------------------------------------------------------------------------

class TestReadiness:
    def test_healthy_when_db_and_redis_ok(self, client):
        """Both backends healthy → 200 ready."""
        with (
            patch("backend.api.health_routes.safe_db_check") as mock_db,
            patch("backend.api.health_routes.redis_conn") as mock_redis,
        ):
            mock_db.return_value = None
            mock_redis.ping.return_value = True

            response = client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_503_when_db_raises_generic_error(self, client):
        """DB raises a plain exception → 503 database unavailable."""
        with (
            patch("backend.api.health_routes.safe_db_check") as mock_db,
            patch("backend.api.health_routes.redis_conn"),
        ):
            mock_db.side_effect = Exception("connection refused")

            response = client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["detail"] == "database unavailable"

    def test_503_when_circuit_breaker_open(self, client):
        """Open circuit breaker → 503 circuit open."""
        with (
            patch("backend.api.health_routes.safe_db_check") as mock_db,
            patch("backend.api.health_routes.redis_conn"),
        ):
            mock_db.side_effect = pybreaker.CircuitBreakerError()

            response = client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["detail"] == "circuit open"

    def test_503_when_redis_unavailable(self, client):
        """DB healthy but Redis unreachable → 503 redis unavailable."""
        with (
            patch("backend.api.health_routes.safe_db_check") as mock_db,
            patch("backend.api.health_routes.redis_conn") as mock_redis,
        ):
            mock_db.return_value = None
            mock_redis.ping.side_effect = Exception("redis down")

            response = client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["detail"] == "redis unavailable"
