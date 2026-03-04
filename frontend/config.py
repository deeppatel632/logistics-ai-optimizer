# frontend/config.py
#
# Central configuration for the Flask dashboard.
# Values are read from environment variables so the same image works in dev,
# staging, and production without code changes.

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class _Config:
    # ── Backend ──────────────────────────────────────────────────────
    fastapi_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "FASTAPI_BASE_URL", "http://localhost:8000"
        )
    )
    request_timeout: float = field(
        default_factory=lambda: float(os.environ.get("API_TIMEOUT", "10"))
    )

    # ── Flask ────────────────────────────────────────────────────────
    flask_secret_key: str = field(
        default_factory=lambda: os.environ.get(
            "FLASK_SECRET_KEY", "dev-secret-change-in-prod"
        )
    )
    flask_port: int = field(
        default_factory=lambda: int(os.environ.get("FLASK_PORT", "5050"))
    )
    flask_debug: bool = field(
        default_factory=lambda: os.environ.get(
            "FLASK_DEBUG", "false"
        ).lower() == "true"
    )

    # ── Polling intervals (seconds, used by frontend JS) ─────────────
    poll_vehicles_s: int = 5
    poll_shipments_s: int = 20
    poll_analytics_s: int = 30
    poll_dashboard_s: int = 15


# Singleton — import this wherever config is needed
settings = _Config()
