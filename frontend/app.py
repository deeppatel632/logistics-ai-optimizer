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
    stats: Dict[str, Any] = {"username": session.get("username", "—")}

    try:
        shipments = _api_get("/shipments")
        if not isinstance(shipments, list):
            shipments = []
    except Exception:
        shipments = []

    try:
        vehicles = _api_get("/streaming/vehicles")
        if not isinstance(vehicles, list):
            vehicles = []
    except Exception:
        vehicles = []

    try:
        kpis = _api_get("/analytics/kpis")
        warehouse_load = kpis.get("warehouse_load", []) if isinstance(kpis, dict) else []
    except Exception:
        warehouse_load = []

    status_counts: Dict[str, int] = {}
    for s in shipments:
        st = s.get("status", "UNKNOWN")
        status_counts[st] = status_counts.get(st, 0) + 1

    stats.update({
        "total_shipments":     len(shipments),
        "active_shipments":    status_counts.get("IN_TRANSIT", 0),
        "delivered_shipments": status_counts.get("DELIVERED", 0),
        "cancelled_shipments": status_counts.get("CANCELLED", 0),
        "created_shipments":   status_counts.get("CREATED", 0),
        "total_vehicles":      len(vehicles),
        "active_vehicles":     sum(1 for v in vehicles if v.get("status") in ("En Route", "en_route", "IN_TRANSIT")),
        "total_warehouses":    len(warehouse_load),
    })
    return render_template("analytics.html", stats=stats, username=session.get("username"))


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


@app.route("/api/inventory")
@login_required
def api_inventory():
    """
    Return per-warehouse inventory utilisation by proxying to
    GET /analytics/kpis → warehouse_load list.

    Each item: {warehouse_id, name, capacity, stock_quantity, utilisation_pct}
    """
    try:
        data = _api_get("/analytics/kpis")
        return jsonify(data.get("warehouse_load", []))
    except httpx.HTTPStatusError as exc:
        return jsonify({"error": str(exc)}), exc.response.status_code
    except httpx.RequestError as exc:
        return jsonify({"error": "backend unreachable", "detail": str(exc)}), 503


@app.route("/api/analytics/data")
@login_required
def api_analytics_data():
    """Aggregate shipments + vehicles + inventory into chart-ready JSON.

    Response shape
    ──────────────
    {
      "kpis":                { total_shipments, active_shipments, delivered_shipments,
                               cancelled_shipments, created_shipments,
                               total_vehicles, active_vehicles, total_warehouses },
      "shipments_over_time": { labels: ["YYYY-MM-DD", ...], data: [n, ...] },
      "status_distribution": { labels: [status, ...], data: [n, ...] },
      "vehicle_utilization": { labels: ["Type #id", ...], data: [n, ...] },
      "inventory_activity":  { labels: [wh_name, ...], stock: [n, ...], capacity: [n, ...] },
    }
    """
    from collections import defaultdict

    # ── Fetch raw data ─────────────────────────────────────────────────────
    shipments: list = []
    vehicles:  list = []
    warehouse_load: list = []

    try:
        raw = _api_get("/shipments")
        shipments = raw if isinstance(raw, list) else []
    except Exception as exc:
        logger.warning("api_analytics_data: /shipments failed — %s", exc)

    try:
        raw = _api_get("/streaming/vehicles")
        vehicles = raw if isinstance(raw, list) else []
    except Exception as exc:
        logger.warning("api_analytics_data: /streaming/vehicles failed — %s", exc)

    try:
        raw = _api_get("/analytics/kpis")
        warehouse_load = raw.get("warehouse_load", []) if isinstance(raw, dict) else []
    except Exception as exc:
        logger.warning("api_analytics_data: /analytics/kpis failed — %s", exc)

    # ── KPI counters ──────────────────────────────────────────────────────
    status_counts: Dict[str, int] = defaultdict(int)
    for s in shipments:
        status_counts[s.get("status", "UNKNOWN")] += 1

    active_statuses = {"En Route", "en_route", "IN_TRANSIT", "Available"}
    kpis = {
        "total_shipments":     len(shipments),
        "active_shipments":    status_counts.get("IN_TRANSIT", 0),
        "delivered_shipments": status_counts.get("DELIVERED", 0),
        "cancelled_shipments": status_counts.get("CANCELLED", 0),
        "created_shipments":   status_counts.get("CREATED", 0),
        "total_vehicles":      len(vehicles),
        "active_vehicles":     sum(1 for v in vehicles if v.get("status") in active_statuses),
        "total_warehouses":    len(warehouse_load),
    }

    # ── Shipments over time (grouped by creation date) ────────────────────
    date_counts: Dict[str, int] = defaultdict(int)
    for s in shipments:
        ts = s.get("created_at") or s.get("createdAt") or ""
        if ts:
            date_counts[str(ts)[:10]] += 1
    sorted_dates = sorted(date_counts)

    # ── Status distribution ───────────────────────────────────────────────
    # Enforce a fixed ordering so the pie chart legend is consistent
    ordered_statuses = ["CREATED", "IN_TRANSIT", "DELIVERED", "CANCELLED"]
    all_statuses = ordered_statuses + [k for k in status_counts if k not in ordered_statuses]
    status_dist_labels = [s for s in all_statuses if s in status_counts]
    status_dist_data   = [status_counts[s] for s in status_dist_labels]

    # ── Vehicle utilisation (shipments handled per vehicle) ───────────────
    vehicle_shipments: Dict[str, int] = defaultdict(int)
    for s in shipments:
        vid = s.get("vehicle_id")
        if vid is not None:
            vehicle_shipments[str(vid)] += 1

    vehicle_labels_map = {
        str(v.get("id", "")): f"{v.get('type', 'Vehicle')} #{v.get('id', '?')}"
        for v in vehicles
    }
    # Top 15 by shipment count
    top_vehicles = sorted(vehicle_shipments.items(), key=lambda x: -x[1])[:15]
    vutil_labels = [vehicle_labels_map.get(vid, f"Vehicle #{vid}") for vid, _ in top_vehicles]
    vutil_data   = [cnt for _, cnt in top_vehicles]

    # ── Inventory activity (stock vs capacity per warehouse) ──────────────
    inv_labels   = [w.get("name") or f"WH {w.get('warehouse_id', '?')}" for w in warehouse_load]
    inv_stock    = [w.get("stock_quantity", 0) for w in warehouse_load]
    inv_capacity = [w.get("capacity", 0) for w in warehouse_load]

    return jsonify({
        "kpis":                kpis,
        "shipments_over_time": {
            "labels": sorted_dates,
            "data":   [date_counts[d] for d in sorted_dates],
        },
        "status_distribution": {
            "labels": status_dist_labels,
            "data":   status_dist_data,
        },
        "vehicle_utilization": {
            "labels": vutil_labels,
            "data":   vutil_data,
        },
        "inventory_activity": {
            "labels":   inv_labels,
            "stock":    inv_stock,
            "capacity": inv_capacity,
        },
    })


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
