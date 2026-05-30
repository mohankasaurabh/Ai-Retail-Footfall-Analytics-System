"""
=====================================================
Heatmap Routes — live + historical movement density
=====================================================

GET /api/cameras/<id>/heatmap?mode=live|historical&range=<key>

Returns movement points (for canvas rendering) plus density
metrics: total points, peak/avg grid density, hot/cold zones
(via point-in-polygon over the camera's zones), an hourly
activity histogram, and a recent-trend series.
"""

from datetime import datetime, timedelta

import numpy as np
import cv2
from flask import Blueprint, request, jsonify

from backend.database import repository
from backend.services.analytics_service import analytics_service


heatmap_bp = Blueprint("heatmaps", __name__)

FRAME_W, FRAME_H = 1280, 720

RANGE_DELTAS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}


def _resolve_range(key):
    if key in RANGE_DELTAS:
        return datetime.utcnow() - RANGE_DELTAS[key], None
    return None, None  # 'all' / unknown


@heatmap_bp.route("/api/cameras/<int:camera_id>/heatmap/live_positions")
def live_positions(camera_id):
    """Current-frame people positions, for the live decaying heatmap."""
    pts = analytics_service.get_positions(camera_id)
    return jsonify({
        "frame": {"w": FRAME_W, "h": FRAME_H},
        "positions": [{"x": p[0], "y": p[1]} for p in pts],
    })


@heatmap_bp.route("/api/cameras/<int:camera_id>/heatmap")
def heatmap(camera_id):
    mode = request.args.get("mode", "live")
    rng = request.args.get("range", "1h")

    if mode == "live":
        # most-recent points, no time filter
        pts = repository.movement_points(camera_id, limit=1500)
    else:
        start, end = _resolve_range(rng)
        pts = repository.movement_points(camera_id, start=start, end=end, limit=5000)

    xs = np.array([p["x"] for p in pts], dtype=float) if pts else np.array([])
    ys = np.array([p["y"] for p in pts], dtype=float) if pts else np.array([])

    # ---- grid density ----
    peak_density = 0
    avg_density = 0.0
    if len(xs):
        grid, _, _ = np.histogram2d(
            xs, ys, bins=[24, 14],
            range=[[0, FRAME_W], [0, FRAME_H]],
        )
        peak_density = int(grid.max())
        nonzero = grid[grid > 0]
        avg_density = round(float(nonzero.mean()), 1) if nonzero.size else 0.0

    # ---- hot / cold zones (point-in-polygon) ----
    zones = repository.list_zones(camera_id)
    zone_counts = []
    for z in zones:
        poly = np.array(z["points"], dtype=np.int32)
        if len(poly) < 3:
            continue
        c = 0
        for p in pts:
            if cv2.pointPolygonTest(poly, (float(p["x"]), float(p["y"])), False) >= 0:
                c += 1
        zone_counts.append({"zone": z["name"], "count": c})
    zone_counts.sort(key=lambda r: r["count"], reverse=True)
    hot = zone_counts[:3]
    cold = sorted(zone_counts, key=lambda r: r["count"])[:3]

    # ---- hourly activity ----
    hours = [0] * 24
    for p in pts:
        if p.get("ts"):
            hours[p["ts"].hour] += 1

    return jsonify({
        "frame": {"w": FRAME_W, "h": FRAME_H},
        "points": [{"x": p["x"], "y": p["y"]} for p in pts],
        "metrics": {
            "total_points": len(pts),
            "peak_density": peak_density,
            "avg_density": avg_density,
            "hot_zones": hot,
            "cold_zones": cold,
        },
        "zone_density": zone_counts,
        "hourly": {"labels": [f"{h:02d}:00" for h in range(24)], "counts": hours},
    })
