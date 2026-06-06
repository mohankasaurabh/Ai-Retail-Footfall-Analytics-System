"""
=====================================================
MediaSourceService — concurrent camera worker registry
=====================================================

Owns the set of running CameraWorkers (one per active source)
and exposes start/stop, status, per-camera frames/metrics, and
an MJPEG generator. Sources themselves are persisted in the DB
(Camera table); this service manages their runtime lifecycle.
"""

import time

from backend.services.camera_worker import CameraWorker
from backend.services.analytics_service import analytics_service
from backend.database import repository


class MediaSourceService:

    def __init__(self):
        self.workers = {}  # camera_id -> CameraWorker

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def start_camera(self, camera_id):
        camera_id = int(camera_id)

        if camera_id in self.workers and self.workers[camera_id]._running:
            return {"success": True, "message": "already running"}

        camera = repository.get_camera(camera_id)
        if not camera:
            return {"success": False, "message": "camera not found"}

        worker = CameraWorker(camera)
        self.workers[camera_id] = worker
        worker.start()
        return {"success": True, "camera_id": camera_id, "status": "starting"}

    def stop_camera(self, camera_id):
        camera_id = int(camera_id)
        worker = self.workers.get(camera_id)
        if not worker:
            repository.set_camera_status(camera_id, "stopped")
            return {"success": True, "message": "not running"}
        worker.stop()
        self.workers.pop(camera_id, None)
        return {"success": True, "camera_id": camera_id, "status": "stopped"}

    def stop_all(self):
        for cid in list(self.workers.keys()):
            self.stop_camera(cid)

    def is_running(self, camera_id):
        w = self.workers.get(int(camera_id))
        return bool(w and w._running)

    # =====================================================
    # FRAMES / METRICS
    # =====================================================

    def get_jpeg(self, camera_id):
        w = self.workers.get(int(camera_id))
        return w.get_jpeg() if w else None

    def get_clean_jpeg(self, camera_id):
        w = self.workers.get(int(camera_id))
        return w.get_clean_jpeg() if w else None

    def get_metrics(self, camera_id):
        return analytics_service.get_camera_metrics(int(camera_id))

    def mjpeg_generator(self, camera_id):
        """Yield multipart MJPEG chunks for a camera."""
        camera_id = int(camera_id)
        boundary = (
            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        )
        while True:
            w = self.workers.get(camera_id)
            if not w or not w._running:
                time.sleep(0.2)
                # keep the connection alive briefly even if stopped
                continue
            jpeg = w.get_jpeg()
            if jpeg is None:
                time.sleep(0.05)
                continue
            yield boundary + jpeg + b"\r\n"
            time.sleep(0.03)

    # =====================================================
    # STATUS
    # =====================================================

    def status_all(self):
        """Merge persisted camera rows with live worker runtime state."""
        cameras = repository.list_cameras()
        out = []
        for c in cameras:
            w = self.workers.get(c["id"])
            runtime = w.info() if w else {
                "running": False, "status": c["status"],
                "paused": False, "fps": 0.0, "error": None,
            }
            out.append({**c,
                        "running": runtime["running"],
                        "runtime_status": runtime["status"],
                        "fps": runtime["fps"],
                        "error": runtime["error"]})
        return out


# global singleton
media_source_service = MediaSourceService()
