"""
=====================================================
Zone Analytics — DB-backed polygon zones
=====================================================

Loads polygon (or rectangle) zones for a specific camera
from the database and provides point-in-polygon location,
live occupancy counts, and overlay drawing.

Zones are reloaded periodically so edits made in the Zone
Editor take effect on the live stream without a restart.
"""

import cv2
import numpy as np

from backend.database import repository


class ZoneAnalytics:

    def __init__(self, camera_id=None, reload_every=60):
        self.camera_id = camera_id
        self.reload_every = reload_every
        self._tick = 0
        self.zones = []          # [{id, name, points(np.int32), color, kind}]
        self.zone_counts = {}    # name -> live count
        self._load()

    # =====================================
    # LOAD / RELOAD FROM DB
    # =====================================

    def _load(self):
        zones = []
        try:
            rows = repository.list_zones(self.camera_id) if self.camera_id else []
        except Exception as exc:
            print(f"[ZONE load error] {exc}")
            rows = []
        for z in rows:
            # queue zones ARE counted here (so their live occupancy shows),
            # but they are drawn red by QueueAnalytics (skipped in draw_zones).
            pts = z.get("points") or []
            if len(pts) < 3:
                continue
            zones.append({
                "id": z["id"],
                "name": z["name"],
                "points": np.array(pts, dtype=np.int32),
                "color": z.get("color", "#00ff99"),
                "kind": z.get("kind", "generic"),
            })
        self.zones = zones
        self.zone_counts = {z["name"]: 0 for z in zones}

    def _maybe_reload(self):
        self._tick += 1
        if self._tick % self.reload_every == 0:
            self._load()

    # =====================================
    # PER-FRAME
    # =====================================

    def reset_counts(self):
        self._maybe_reload()
        for name in self.zone_counts:
            self.zone_counts[name] = 0

    def locate(self, centroid):
        """Return the zone dict containing the point, or None."""
        x, y = int(centroid[0]), int(centroid[1])
        for z in self.zones:
            if cv2.pointPolygonTest(z["points"], (x, y), False) >= 0:
                return z
        return None

    def update(self, centroid):
        """Increment live occupancy for the containing zone; return its name."""
        z = self.locate(centroid)
        if z:
            self.zone_counts[z["name"]] = self.zone_counts.get(z["name"], 0) + 1
            return z["name"]
        return "Unknown"

    def get_zone(self, centroid):
        z = self.locate(centroid)
        return z["name"] if z else "Unknown"

    # =====================================
    # DRAW
    # =====================================

    @staticmethod
    def _hex_to_bgr(hex_color):
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return (b, g, r)
        except Exception:
            return (0, 255, 255)

    def draw_zones(self, frame):
        overlay = frame.copy()
        for z in self.zones:
            if z["kind"] == "queue":
                continue   # queue zones are drawn red by QueueAnalytics
            bgr = self._hex_to_bgr(z["color"])
            cv2.polylines(frame, [z["points"]], True, bgr, 2)
            cv2.fillPoly(overlay, [z["points"]], bgr)
            x, y = z["points"][0]
            cv2.putText(
                frame, f"{z['name']}: {self.zone_counts.get(z['name'], 0)}",
                (int(x) + 8, int(y) + 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, bgr, 2,
            )
        # translucent fill
        cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)
        return frame

    def get_total_occupancy(self):
        return sum(self.zone_counts.values())
