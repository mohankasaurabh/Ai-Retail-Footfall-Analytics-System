"""
=====================================================
Queue Analytics — DB-backed editable queue area
=====================================================

The queue area is no longer hardcoded. It is defined by the
zone(s) with kind == "queue" for the camera, drawn/edited/
deleted from the Zone Editor like any other zone. If no queue
zone exists, no queue area is drawn and queue metrics are zero.

Zones are reloaded periodically so edits apply live.
"""

import time

import cv2
import numpy as np

from backend.database import repository


class QueueAnalytics:

    def __init__(self, camera_id=None, reload_every=60):
        self.camera_id = camera_id
        self.reload_every = reload_every
        self._tick = 0
        self.queue_polys = []          # list of np.int32 polygons (kind == queue)
        self.waiting_customers = {}     # reid_id -> entry time
        self.queue_length = 0
        self.average_wait = 0
        self._load()

    # =====================================
    # LOAD / RELOAD QUEUE ZONES
    # =====================================

    def _load(self):
        polys = []
        try:
            rows = repository.list_zones(self.camera_id) if self.camera_id else []
        except Exception as exc:
            print(f"[QUEUE load error] {exc}")
            rows = []
        for z in rows:
            if z.get("kind") != "queue":
                continue
            pts = z.get("points") or []
            if len(pts) >= 3:
                polys.append(np.array(pts, dtype=np.int32))
        self.queue_polys = polys

    def _maybe_reload(self):
        self._tick += 1
        if self._tick % self.reload_every == 0:
            self._load()

    # =====================================
    # INSIDE QUEUE AREA
    # =====================================

    def inside_queue_zone(self, centroid):
        if not self.queue_polys:
            return False
        x, y = int(centroid[0]), int(centroid[1])
        for poly in self.queue_polys:
            if cv2.pointPolygonTest(poly, (x, y), False) >= 0:
                return True
        return False

    # =====================================
    # UPDATE
    # =====================================

    def update(self, reid_id, centroid):
        self._maybe_reload()
        current_time = time.time()

        if self.inside_queue_zone(centroid):
            if reid_id not in self.waiting_customers:
                self.waiting_customers[reid_id] = current_time
        else:
            self.waiting_customers.pop(reid_id, None)

        self.queue_length = len(self.waiting_customers)

        waits = [current_time - t for t in self.waiting_customers.values()]
        self.average_wait = (sum(waits) / len(waits)) if waits else 0

    # =====================================
    # STATUS
    # =====================================

    def get_status(self):
        if self.queue_length >= 10:
            return "HIGH"
        if self.queue_length >= 5:
            return "MEDIUM"
        return "LOW"

    # =====================================
    # DRAW
    # =====================================

    def draw_queue_zone(self, frame):
        for poly in self.queue_polys:
            cv2.polylines(frame, [poly], True, (0, 0, 255), 2)
            x, y = poly[0]
            cv2.putText(
                frame, "QUEUE AREA", (int(x) + 8, int(y) + 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
            )
        return frame
