# simulator/utils.py
#
# Pure-function geo and movement helpers for the truck telemetry simulator.
# No I/O, no side-effects — easy to unit-test independently of the simulator.
#
# Public API
# ──────────
# haversine_m(lat1, lon1, lat2, lon2)       → float  metres between two points
# bearing_degrees(lat1, lon1, lat2, lon2)   → float  compass bearing 0-360
# step_toward(cur, dst, speed_kmph, dt_s)   → (lat, lon)  one movement step
# generate_route_points(start, end, steps)  → List[(lat, lon)]  lin-interp waypoints
# simulate_movement(route_points)           → Generator[(lat, lon)]
# now_iso()                                 → str  current UTC timestamp

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Generator, List, Tuple

# ── Type aliases ─────────────────────────────────────────────────────────────
LatLon = Tuple[float, float]

# ── Earth model ──────────────────────────────────────────────────────────────
_EARTH_R_M = 6_371_000.0  # mean radius in metres


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in **metres** between two WGS-84 points.

    Uses the haversine formula — accurate to within ~0.5 % for distances up
    to a few thousand kilometres.

    Parameters
    ----------
    lat1, lon1 : float
        Origin coordinates in decimal degrees.
    lat2, lon2 : float
        Destination coordinates in decimal degrees.

    Returns
    -------
    float
        Distance in metres.

    Examples
    --------
    >>> round(haversine_m(51.5, -0.1, 48.8, 2.3))
    341551
    """
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat  = math.radians(lat2 - lat1)
    dlon  = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_R_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Bearing
# ---------------------------------------------------------------------------

def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the initial bearing (0–360 °, clockwise from North) from point 1
    to point 2.

    Parameters
    ----------
    lat1, lon1 : float
        Origin coordinates in decimal degrees.
    lat2, lon2 : float
        Destination coordinates in decimal degrees.

    Returns
    -------
    float
        Bearing in degrees [0, 360).

    Examples
    --------
    >>> round(bearing_degrees(0, 0, 0, 1))   # due East
    90
    """
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlon  = math.radians(lon2 - lon1)

    x = math.sin(dlon) * math.cos(rlat2)
    y = (
        math.cos(rlat1) * math.sin(rlat2)
        - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    )
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# ---------------------------------------------------------------------------
# Movement step
# ---------------------------------------------------------------------------

def step_toward(
    cur_lat: float,
    cur_lon: float,
    dst_lat: float,
    dst_lon: float,
    speed_kmph: float,
    dt_s: float,
    jitter_deg: float = 0.0002,
) -> LatLon:
    """Advance a vehicle one time-step toward its destination.

    The vehicle travels ``speed_kmph`` km/h for ``dt_s`` seconds along the
    great-circle bearing.  Small random jitter is added to both axes to mimic
    road-noise from a real GPS receiver.

    Parameters
    ----------
    cur_lat, cur_lon : float
        Current position in decimal degrees.
    dst_lat, dst_lon : float
        Destination position in decimal degrees.
    speed_kmph : float
        Cruising speed in kilometres per hour.
    dt_s : float
        Elapsed time in seconds for this step.
    jitter_deg : float
        Maximum random positional noise in decimal degrees (default 0.0002 ≈ 22 m).

    Returns
    -------
    (float, float)
        New ``(latitude, longitude)`` after this step.
        If the vehicle is already within 1 m of the destination returns the
        destination exactly (no jitter).
    """
    dist_m = haversine_m(cur_lat, cur_lon, dst_lat, dst_lon)
    if dist_m < 1.0:
        return dst_lat, dst_lon

    # Distance the truck covers in this interval
    step_m = (speed_kmph * 1_000.0 / 3_600.0) * dt_s
    ratio  = min(step_m / dist_m, 1.0)

    new_lat = cur_lat + ratio * (dst_lat - cur_lat)
    new_lon = cur_lon + ratio * (dst_lon - cur_lon)

    # GPS road-noise jitter
    new_lat += random.uniform(-jitter_deg, jitter_deg)
    new_lon += random.uniform(-jitter_deg, jitter_deg)

    return new_lat, new_lon


# ---------------------------------------------------------------------------
# Route generation
# ---------------------------------------------------------------------------

def generate_route_points(
    start: LatLon,
    end: LatLon,
    steps: int,
    jitter_deg: float = 0.005,
) -> List[LatLon]:
    """Pre-compute a list of ``steps`` waypoints between ``start`` and ``end``.

    Waypoints are linearly interpolated on lat/lon with a smooth random
    perpendicular deviation added to create a more realistic curved path.

    Parameters
    ----------
    start : (float, float)
        Origin ``(latitude, longitude)`` in decimal degrees.
    end : (float, float)
        Destination ``(latitude, longitude)`` in decimal degrees.
    steps : int
        Number of intermediate waypoints to produce (inclusive of ``start``
        and ``end``).
    jitter_deg : float
        Maximum random perpendicular deviation in degrees (default ≈ 560 m).

    Returns
    -------
    List[(float, float)]
        Ordered list of ``(latitude, longitude)`` waypoints.

    Notes
    -----
    The list always starts with ``start`` and ends with ``end``; intermediate
    points have a bell-shaped lateral deviation that peaks in the middle and
    fades to zero at both endpoints, giving the route a natural arc.
    """
    if steps < 2:
        return [start, end]

    lat1, lon1 = start
    lat2, lon2 = end
    points: List[LatLon] = []

    for i in range(steps):
        t = i / (steps - 1)  # 0.0 → 1.0

        # Linear interpolation
        lat = lat1 + t * (lat2 - lat1)
        lon = lon1 + t * (lon2 - lon1)

        # Perpendicular arc deviation — bell curve peak at t=0.5
        arc = math.sin(math.pi * t) * random.uniform(-jitter_deg, jitter_deg)
        # Rotate the deviation 90° relative to the route direction
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        norm = math.hypot(dlat, dlon) or 1.0
        lat += arc * (-dlon / norm)
        lon += arc * ( dlat / norm)

        points.append((lat, lon))

    return points


# ---------------------------------------------------------------------------
# Movement generator
# ---------------------------------------------------------------------------

def simulate_movement(route_points: List[LatLon]) -> Generator[LatLon, None, None]:
    """Yield each waypoint in ``route_points`` one at a time.

    Intended to be consumed inside a truck's movement loop::

        for lat, lon in simulate_movement(route):
            send_telemetry(vehicle_id, lat, lon)
            time.sleep(INTERVAL_S)

    Parameters
    ----------
    route_points : List[(float, float)]
        Ordered waypoints as returned by :func:`generate_route_points`.

    Yields
    ------
    (float, float)
        Next ``(latitude, longitude)`` waypoint.
    """
    for point in route_points:
        yield point


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with 'Z' suffix.

    Used for the ``timestamp`` field in every telemetry POST.

    Returns
    -------
    str
        e.g. ``"2026-03-04T10:15:00Z"``
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
