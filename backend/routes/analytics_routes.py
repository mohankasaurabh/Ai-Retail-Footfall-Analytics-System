from datetime import datetime

from flask import Blueprint
from flask import jsonify

from backend.services.analytics_service import (
    analytics_service
)

from backend.database.queries import (
    DatabaseManager
)

from backend.database import repository
from backend.database.db_writer import db_writer
from backend.services.media_source_service import media_source_service

# =====================================
# DATABASE
# =====================================

db_manager = DatabaseManager()

# =====================================
# BLUEPRINT
# =====================================

analytics_bp = Blueprint(

    "analytics",

    __name__
)

# =====================================
# LIVE DASHBOARD METRICS
# =====================================

@analytics_bp.route("/analytics")
def analytics():

    data = (
        analytics_service
        .get_dashboard_metrics()
    )

    return jsonify(data)

# =====================================
# LIVE CHART DATA
# =====================================

@analytics_bp.route("/chart_data")
def chart_data():

    data = (
        analytics_service
        .get_chart_data()
    )

    return jsonify(data)

# =====================================
# HISTORICAL DATABASE DATA
# =====================================

@analytics_bp.route("/historical_data")
def historical_data():

    try:

        data = (
            db_manager
            .get_occupancy_history()
        )

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "error": str(e)

        }), 500

# =====================================
# ZONE ANALYTICS
# =====================================

@analytics_bp.route("/zone_data")
def zone_data():

    metrics = (
        analytics_service
        .get_dashboard_metrics()
    )

    return jsonify(

        metrics.get(
            "zone_data",
            {}
        )
    )

# =====================================
# QUEUE ANALYTICS
# =====================================

@analytics_bp.route("/queue_data")
def queue_data():

    metrics = (
        analytics_service
        .get_dashboard_metrics()
    )

    return jsonify({

        "queue_length":
            metrics.get(
                "queue_length",
                0
            ),

        "average_wait":
            metrics.get(
                "average_wait",
                0
            ),

        "queue_status":
            metrics.get(
                "queue_status",
                "LOW"
            )
    })

# =====================================
# JOURNEY ANALYTICS
# =====================================

@analytics_bp.route("/journey_data")
def journey_data():

    metrics = (
        analytics_service
        .get_dashboard_metrics()
    )

    return jsonify({

        "journey_customers":
            metrics.get(
                "journey_customers",
                0
            )
    })

# =====================================
# SYSTEM HEALTH
# =====================================

@analytics_bp.route("/system_status")
def system_status():

    metrics = (
        analytics_service
        .get_dashboard_metrics()
    )

    return jsonify({

        "status":
            "running",

        "occupancy":
            metrics.get(
                "occupancy",
                0
            ),

        "tracks":
            metrics.get(
                "total_tracks",
                0
            ),

        "reid":
            metrics.get(
                "reid_identities",
                0
            )
    })


# =====================================
# DEMOGRAPHICS DISTRIBUTION
# =====================================

@analytics_bp.route("/api/demographics")
def api_demographics():
    """Gender split + age-group distribution from live profiles."""

    metrics = analytics_service.get_dashboard_metrics()

    buckets = {
        "0-17": 0,
        "18-25": 0,
        "26-35": 0,
        "36-50": 0,
        "51+": 0
    }

    for profile in analytics_service.customer_profiles.values():

        try:
            age = int(profile.get("age", 0))
        except (TypeError, ValueError):
            continue

        if age <= 17:
            buckets["0-17"] += 1
        elif age <= 25:
            buckets["18-25"] += 1
        elif age <= 35:
            buckets["26-35"] += 1
        elif age <= 50:
            buckets["36-50"] += 1
        else:
            buckets["51+"] += 1

    return jsonify({
        "male": metrics.get("male_count", 0),
        "female": metrics.get("female_count", 0),
        "age_labels": list(buckets.keys()),
        "age_values": list(buckets.values())
    })


# =====================================
# FOOTFALL (hourly aggregation)
# =====================================

@analytics_bp.route("/api/footfall")
def api_footfall():
    try:
        return jsonify(db_manager.get_hourly_footfall())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# =====================================
# HEATMAP DATA (movement points)
# =====================================

@analytics_bp.route("/api/heatmap_data")
def api_heatmap_data():
    try:
        points = db_manager.get_movement_points(limit=3000)
        return jsonify({"points": points})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# =====================================
# ZONE RANKING (top + dead zones)
# =====================================

@analytics_bp.route("/api/zone_ranking")
def api_zone_ranking():

    metrics = analytics_service.get_dashboard_metrics()
    zone_data = metrics.get("zone_data", {}) or {}

    ranked = sorted(
        zone_data.items(),
        key=lambda kv: kv[1],
        reverse=True
    )

    return jsonify({
        "zones": [
            {"zone": z, "count": c}
            for z, c in ranked
        ],
        "top": [
            {"zone": z, "count": c}
            for z, c in ranked[:3]
        ],
        "dead": [
            {"zone": z, "count": c}
            for z, c in ranked if c == 0
        ]
    })


# =====================================
# CUSTOMER JOURNEY LIST
# =====================================

@analytics_bp.route("/api/journey_list")
def api_journey_list():
    """List tracked customer profiles for the journey page."""

    customers = []

    for track_id, profile in analytics_service.customer_profiles.items():
        customers.append({
            "customer_id": track_id,
            "age": profile.get("age", "—"),
            "gender": profile.get("gender", "—")
        })

    return jsonify({
        "total": len(customers),
        "customers": customers
    })


# =====================================
# EXECUTIVE DASHBOARD
# =====================================

def _age_buckets():
    buckets = {"0-17": 0, "18-25": 0, "26-35": 0, "36-50": 0, "51+": 0}
    for p in analytics_service.customer_profiles.values():
        try:
            age = int(p.get("age", 0))
        except (TypeError, ValueError):
            continue
        if age <= 17:
            buckets["0-17"] += 1
        elif age <= 25:
            buckets["18-25"] += 1
        elif age <= 35:
            buckets["26-35"] += 1
        elif age <= 50:
            buckets["36-50"] += 1
        else:
            buckets["51+"] += 1
    return buckets


@analytics_bp.route("/api/dashboard")
def api_dashboard():
    """Executive KPIs + realtime overview + system health."""

    agg = analytics_service.aggregate()

    # runtime camera state
    cameras = media_source_service.status_all()
    active_cameras = sum(1 for c in cameras if c.get("running"))
    cameras_total = len(cameras)

    # active zones = zones on currently-running cameras
    active_zones = 0
    for c in cameras:
        if c.get("running"):
            active_zones += len(repository.list_zones(c["id"]))

    # today's rollups
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    snaps = repository.snapshots_in_range(start=start)
    today_visitors = max((s["unique_customers"] for s in snaps), default=agg["total_tracks"])

    # peak hour by occupancy
    peak_hour = "—"
    if snaps:
        by_hour = {}
        for s in snaps:
            hr = s["ts"][11:13]
            by_hour[hr] = max(by_hour.get(hr, 0), s["occupancy"])
        peak_hour = max(by_hour, key=by_hour.get) + ":00"

    return jsonify({
        "kpi": {
            "current_footfall": agg["occupancy"],
            "today_visitors": today_visitors,
            "peak_hour": peak_hour,
            "avg_dwell": repository.recent_avg_dwell() or agg["avg_dwell"],
            "active_cameras": active_cameras,
            "active_zones": active_zones,
        },
        "realtime": {
            "live_count": agg["occupancy"],
            "male": agg["male_count"],
            "female": agg["female_count"],
            "age": _age_buckets(),
        },
        "system_health": {
            "db_writer": True,
            "cameras_online": active_cameras,
            "cameras_total": cameras_total,
        },
    })