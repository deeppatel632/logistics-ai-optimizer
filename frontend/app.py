# frontend/app.py
#
# Flask dashboard — proxies all data requests to the FastAPI backend using
# HTTPX.  Sessions store only the JWT token; all business logic stays in
# the backend.
#
# Pages
# ─────
# GET  /login                   login form
# POST /login                   authenticate → store JWT in session
# GET  /logout                  clear session
# GET  /                        redirect → /dashboard
# GET  /dashboard               admin overview
# GET  /vehicles                realtime vehicle map
# GET  /shipments               shipment management panel
# GET  /inventory               warehouse inventory view
# GET  /analytics               KPI analytics dashboard
#
# API proxy helpers (called via fetch() from JS or Jinja templates)
# ─────────────────────────────────────────────────────────────────
# GET  /api/vehicles            → FastAPI /streaming/vehicles
# GET  /api/shipments           → FastAPI /shipments
# GET  /api/warehouses          → FastAPI /warehouses
# GET  /api/inventory           → FastAPI /inventory
# GET  /api/analytics/summary   aggregate stats
# POST /api/shipments           → FastAPI POST /shipments
# POST /api/vehicles/location   → FastAPI POST /streaming/location

import logging
import os
from functools import wraps
from typing import Any, Dict, Optional

import httpx
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-prod")

FASTAPI_BASE = os.environ.get("FASTAPI_BASE_URL", "http://localhost:8000")
REQUEST_TIMEOUT = 10.0  # seconds

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: synchronous HTTPX client factory
# ---------------------------------------------------------------------------

def _api_client() -> httpx.Client:
    """Return a configured HTTPX client with the stored JWT attached."""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    token: Optional[str] = session.get("access_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(
        base_url=FASTAPI_BASE,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )


def _api_get(path: str) -> Any:
    with _api_client() as client:
        r = client.get(path)
        r.raise_for_status()
        return r.json()


def _api_post(path: str, payload: Dict) -> Any:
    with _api_client() as client:
        r = client.post(path, json=payload)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Auth guard decorator
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("access_token"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET"])
def login_page():
    if session.get("access_token"):
        return redirect(url_for("dashboard"))
    return render_template("login.html", error=None)


@app.route("/login", methods=["POST"])
def login_submit():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    try:
        with httpx.Client(base_url=FASTAPI_BASE, timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(
                "/auth/login",
                data={"username": username, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if resp.status_code == 200:
            data = resp.json()
            session["access_token"] = data["access_token"]
            session["username"] = username
            logger.info("dashboard_login username=%s", username)
            return redirect(url_for("dashboard"))

        error = "Invalid username or password."
    except httpx.RequestError as exc:
        logger.error("login_request_error %s", exc)
        error = "Could not reach the backend API. Please try again."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/")
@login_required
def index():
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    try:
        health = _api_get("/health/ready")
    except Exception:
        health = {"status": "unknown"}

    # Gather quick counts for the stat cards
    stats: Dict[str, Any] = {
        "api_status": health.get("status", "unknown"),
        "username": session.get("username", "—"),
    }

    try:
        warehouses = _api_get("/warehouses")
        stats["warehouse_count"] = len(warehouses) if isinstance(warehouses, list) else "—"
    except Exception:
        stats["warehouse_count"] = "—"

    return render_template("dashboard.html", stats=stats)


@app.route("/vehicles")
@login_required
def vehicles_page():
    return render_template("vehicles.html", username=session.get("username"))


@app.route("/shipments")
@login_required
def shipments_page():
    try:
        shipments = _api_get("/shipments")
    except Exception:
        shipments = []
    return render_template("shipments.html", shipments=shipments, username=session.get("username"))


@app.route("/inventory")
@login_required
def inventory_page():
    try:
        warehouses = _api_get("/warehouses")
    except Exception:
        warehouses = []
    return render_template("inventory.html", warehouses=warehouses, username=session.get("username"))


@app.route("/analytics")
@login_required
def analytics_page():
    return render_template("analytics.html", username=session.get("username"))


# ---------------------------------------------------------------------------
# JSON API proxy endpoints (called from JS fetch())
# ---------------------------------------------------------------------------

@app.route("/api/vehicles")
@login_required
def api_vehicles():
    try:
        data = _api_get("/streaming/vehicles")
        return jsonify(data)
    except httpx.HTTPStatusError as exc:
        return jsonify({"error": str(exc)}), exc.response.status_code
    except httpx.RequestError as exc:
        return jsonify({"error": "backend unreachable", "detail": str(exc)}), 503


@app.route("/api/shipments")
@login_required
def api_shipments():
    try:
        data = _api_get("/shipments")
        return jsonify(data)
    except httpx.HTTPStatusError as exc:
        return jsonify({"error": str(exc)}), exc.response.status_code
    except httpx.RequestError as exc:
        return jsonify({"error": "backend unreachable"}), 503


@app.route("/api/shipments", methods=["POST"])
@login_required
def api_create_shipment():
    payload = request.get_json(force=True)
    try:
        data = _api_post("/shipments", payload)
        return jsonify(data), 201
    except httpx.HTTPStatusError as exc:
        return jsonify({"error": exc.response.text}), exc.response.status_code
    except httpx.RequestError as exc:
        return jsonify({"error": "backend unreachable"}), 503


@app.route("/api/warehouses")
@login_required
def api_warehouses():
    try:
        data = _api_get("/warehouses")
        return jsonify(data)
    except httpx.HTTPStatusError as exc:
        return jsonify({"error": str(exc)}), exc.response.status_code
    except httpx.RequestError as exc:
        return jsonify({"error": "backend unreachable"}), 503


@app.route("/api/analytics/summary")
@login_required
def api_analytics_summary():
    """Proxy directly to the FastAPI /analytics/summary endpoint."""
    try:
        data = _api_get("/analytics/summary")
        return jsonify(data)
    except httpx.HTTPStatusError as exc:
        return jsonify({"error": str(exc)}), exc.response.status_code
    except httpx.RequestError as exc:
        return jsonify({"error": "backend unreachable"}), 503


@app.route("/api/analytics/kpis")
@login_required
def api_analytics_kpis():
    """Proxy to /analytics/kpis — warehouse utilisation + truck utilisation."""
    try:
        data = _api_get("/analytics/kpis")
        return jsonify(data)
    except httpx.HTTPStatusError as exc:
        return jsonify({"error": str(exc)}), exc.response.status_code
    except httpx.RequestError as exc:
        return jsonify({"error": "backend unreachable"}), 503


@app.route("/api/vehicles/location", methods=["POST"])
@login_required
def api_vehicle_location():
    payload = request.get_json(force=True)
    try:
        data = _api_post("/streaming/vehicle-location", payload)
        return jsonify(data)
    except httpx.HTTPStatusError as exc:
        return jsonify({"error": exc.response.text}), exc.response.status_code
    except httpx.RequestError as exc:
        return jsonify({"error": "backend unreachable"}), 503


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
