"""
=====================================================
Analytics Service (per-camera namespacing)
=====================================================

Holds live metric state, now partitioned per camera so the
concurrent multi-camera engine (Phase 2) can write independent
state. Backward compatible: callers that omit camera_id write
to a single DEFAULT_CAMERA bucket, and get_dashboard_metrics()
with no argument returns an AGGREGATE across all cameras — so
the existing single-camera dashboard keeps working unchanged.

DB writes go through the batched async writer (thread-safe),
not a shared Session.
"""

import time

from backend.database.db_writer import db_writer
from backend.database.models import AnalyticsLog, MovementLog
from backend.database import repository


DEFAULT_CAMERA = "default"

# numeric KPI fields that SUM across cameras
_SUM_KEYS = [
    "occupancy", "entries", "exits", "active_customers",
    "zone_occupancy", "total_tracks", "male_count", "female_count",
    "journey_customers", "queue_length",
]
# global counts that should NOT sum (take the max across cameras)
_MAX_KEYS = [
    "reid_identities", "multi_camera_customers",
    "cross_camera_customers", "average_wait", "avg_dwell",
]

_QUEUE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _empty_metrics():
    return {
        "occupancy": 0, "entries": 0, "exits": 0, "active_customers": 0,
        "zone_occupancy": 0, "total_tracks": 0, "reid_identities": 0,
        "male_count": 0, "female_count": 0, "journey_customers": 0,
        "queue_length": 0, "average_wait": 0, "queue_status": "LOW",
        "cross_camera_customers": 0, "multi_camera_customers": 0,
        "avg_dwell": 0.0, "zone_data": {},
    }


class AnalyticsService:

    def __init__(self):
        # camera_id -> metrics dict
        self.cameras = {}
        # camera_id -> set of seen track ids
        self.seen_track_ids = {}
        # global cross-camera customer profiles (keyed by reid/track id)
        self.customer_profiles = {}

        # current-frame people positions per camera (for live decaying heatmap)
        self.positions = {}  # camera_id -> [[x, y], ...]

        # aggregate rolling history for live charts (back-compat)
        self.history = {
            "timestamps": [], "occupancy": [], "entries": [], "zone_occupancy": [],
        }

        self.last_save_time = time.time()
        self.save_interval = 5

    # =====================================
    # PER-CAMERA ACCESS
    # =====================================

    def _cam(self, camera_id):
        if camera_id not in self.cameras:
            self.cameras[camera_id] = _empty_metrics()
            self.seen_track_ids[camera_id] = set()
        return self.cameras[camera_id]

    def reset_camera(self, camera_id):
        self.cameras[camera_id] = _empty_metrics()
        self.seen_track_ids[camera_id] = set()

    # =====================================
    # TRACKING METRICS
    # =====================================

    def update_tracking_metrics(self, tracked_objects, camera_id=DEFAULT_CAMERA):
        m = self._cam(camera_id)
        seen = self.seen_track_ids[camera_id]

        current = set()
        for obj in tracked_objects:
            tid = obj["track_id"]
            current.add(tid)
            if tid not in seen:
                seen.add(tid)
                m["entries"] += 1

        m["occupancy"] = len(current)
        m["active_customers"] = len(current)
        m["total_tracks"] = len(seen)

        self._store_history()
        self._auto_save()

    # =====================================
    # ZONE / REID / DEMOGRAPHICS / JOURNEY / QUEUE
    # =====================================

    def update_zone_data(self, zone_counts, camera_id=DEFAULT_CAMERA):
        m = self._cam(camera_id)
        m["zone_data"] = zone_counts
        m["zone_occupancy"] = sum(zone_counts.values())

    def set_reid_identities(self, count, camera_id=DEFAULT_CAMERA):
        self._cam(camera_id)["reid_identities"] = count

    def update_demographics(self, demographic_results, camera_id=DEFAULT_CAMERA):
        m = self._cam(camera_id)
        male = female = 0
        for r in demographic_results:
            if r.get("gender") == "Man":
                male += 1
            else:
                female += 1
        m["male_count"] = male
        m["female_count"] = female

    def update_customer_profile(self, demographic_result):
        if not demographic_result:
            return
        # prefer persistent reid_id when available, else track_id
        key = demographic_result.get("reid_id") or demographic_result.get("track_id")
        if key is None:
            return
        self.customer_profiles[key] = {
            "age": demographic_result["age"],
            "gender": demographic_result["gender"],
        }

    def update_journey_metrics(self, total_customers, camera_id=DEFAULT_CAMERA):
        self._cam(camera_id)["journey_customers"] = total_customers

    def update_queue_metrics(self, queue_length, average_wait, status,
                             camera_id=DEFAULT_CAMERA):
        m = self._cam(camera_id)
        m["queue_length"] = queue_length
        m["average_wait"] = round(average_wait, 1)
        m["queue_status"] = status

    def update_cross_camera(self, count, camera_id=DEFAULT_CAMERA):
        self._cam(camera_id)["cross_camera_customers"] = count

    def update_multi_camera_metrics(self, count, camera_id=DEFAULT_CAMERA):
        self._cam(camera_id)["multi_camera_customers"] = count

    def set_avg_dwell(self, seconds, camera_id=DEFAULT_CAMERA):
        self._cam(camera_id)["avg_dwell"] = round(seconds, 1)

    # =====================================
    # CURRENT POSITIONS (live heatmap)
    # =====================================

    def set_positions(self, camera_id, positions):
        self.positions[camera_id] = positions

    def get_positions(self, camera_id):
        return self.positions.get(camera_id, [])

    # =====================================
    # MOVEMENT LOGGING (async batched write)
    # =====================================

    def log_movement(self, track_id, centroid, camera_id=DEFAULT_CAMERA):
        x, y = centroid
        db_writer.enqueue(MovementLog(track_id=track_id, x=x, y=y))

    # =====================================
    # PERSISTENCE (rollup)
    # =====================================

    def _auto_save(self):
        now = time.time()
        if now - self.last_save_time >= self.save_interval:
            agg = self.aggregate()
            # legacy table (read by current endpoints)
            db_writer.enqueue(AnalyticsLog(
                occupancy=agg["occupancy"], entries=agg["entries"],
                exits=agg["exits"], active_customers=agg["active_customers"],
                zone_occupancy=agg["zone_occupancy"],
                total_tracks=agg["total_tracks"],
                reid_identities=agg["reid_identities"],
            ))
            # new rollup table
            try:
                repository.add_snapshot(agg)
            except Exception as exc:
                print(f"[ANALYTICS snapshot error] {exc}")
            self.last_save_time = now

    # =====================================
    # HISTORY (aggregate)
    # =====================================

    def _store_history(self):
        agg = self.aggregate()
        self.history["timestamps"].append(time.strftime("%H:%M:%S"))
        self.history["occupancy"].append(agg["occupancy"])
        self.history["entries"].append(agg["entries"])
        self.history["zone_occupancy"].append(agg["zone_occupancy"])
        if len(self.history["timestamps"]) > 30:
            for k in self.history:
                self.history[k].pop(0)

    # =====================================
    # AGGREGATION
    # =====================================

    def aggregate(self):
        agg = _empty_metrics()
        if not self.cameras:
            return agg

        for m in self.cameras.values():
            for k in _SUM_KEYS:
                agg[k] += m.get(k, 0)
            for k in _MAX_KEYS:
                agg[k] = max(agg[k], m.get(k, 0))
            # merge zone data
            for zname, zcount in (m.get("zone_data") or {}).items():
                agg["zone_data"][zname] = agg["zone_data"].get(zname, 0) + zcount
            # highest queue severity wins
            if _QUEUE_RANK.get(m.get("queue_status", "LOW"), 0) > \
               _QUEUE_RANK.get(agg["queue_status"], 0):
                agg["queue_status"] = m["queue_status"]

        return agg

    # =====================================
    # PUBLIC READS
    # =====================================

    def get_dashboard_metrics(self, camera_id=None):
        if camera_id is not None:
            return dict(self._cam(camera_id))
        return self.aggregate()

    def get_camera_metrics(self, camera_id):
        return dict(self._cam(camera_id))

    def list_camera_ids(self):
        return list(self.cameras.keys())

    def get_chart_data(self):
        return self.history


# =====================================
# GLOBAL ANALYTICS SERVICE
# =====================================

analytics_service = AnalyticsService()
