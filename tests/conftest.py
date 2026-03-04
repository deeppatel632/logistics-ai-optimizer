# tests/conftest.py
#
# IMPORTANT: os.environ overrides MUST be set before any backend module is
# imported, because pydantic-settings reads them at class instantiation time.
# Python executes this file top-to-bottom, so setting env vars here —
# before the `import pytest` line — guarantees they are present when the
# first `from backend.xxx import ...` statement resolves.

import os

# ---------------------------------------------------------------------------
# Minimal test environment — used both locally (as os.environ fallbacks)
# and in CI (where no .env file exists).  setdefault() means a .env file
# that already has real values is never overwritten during local runs.
# ---------------------------------------------------------------------------
_TEST_ENV = {
    "APP_ENV": "test",
    "DEBUG": "false",
    "API_HOST": "0.0.0.0",
    "API_PORT": "8000",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test_pass",
    "DB_SERVER": "localhost",
    "DB_PORT": "1433",
    "DB_NAME": "test_db",
    "DB_DRIVER": "ODBC Driver 18 for SQL Server",
    "PRIMARY_DB_URL": (
        "mssql+pyodbc://test_user:test_pass@localhost:1433/test_db"
        "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
    ),
    "REPLICA_DB_URL": (
        "mssql+pyodbc://test_user:test_pass@localhost:1433/test_db"
        "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
    ),
    "DB_POOL_SIZE": "2",
    "DB_MAX_OVERFLOW": "2",
    "DB_POOL_TIMEOUT": "5",
    "DB_POOL_RECYCLE": "300",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_DB": "0",
    "JWT_SECRET": "ci-test-secret-key-not-for-production",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}

for _key, _val in _TEST_ENV.items():
    os.environ.setdefault(_key, _val)

# ---------------------------------------------------------------------------
# Standard imports (after env vars are set)
# ---------------------------------------------------------------------------
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    """Import the FastAPI app once per test session."""
    from backend.main import app as _app
    return _app


@pytest.fixture(scope="session")
def db_overrides(app):
    """
    Replace all database session dependencies with a MagicMock for the
    entire test session.  Cleared after the session finishes.
    """
    from database.connection import get_db, get_write_db, get_read_db

    mock_session = MagicMock()

    app.dependency_overrides[get_db] = lambda: mock_session
    app.dependency_overrides[get_write_db] = lambda: mock_session
    app.dependency_overrides[get_read_db] = lambda: mock_session

    yield mock_session

    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def client(app, db_overrides):
    """
    Return a TestClient that does NOT run startup events (no `with` block),
    so `validate_database_connection` is never called against a real DB.
    """
    return TestClient(app, raise_server_exceptions=True)
