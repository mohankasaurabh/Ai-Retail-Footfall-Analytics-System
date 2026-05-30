"""
=====================================================
CameraWorker — one daemon thread per active source
=====================================================

Captures from a single source, runs its own Pipeline, and
publishes the latest annotated JPEG + live metrics into
thread-safe slots that routes read for MJPEG / snapshots.

Multiple workers run concurrently (true multi-camera). A
per-source FPS throttle keeps total load manageable on a
single machine.
"""

import threading
import time

import cv2

from backend.services.pipeline import Pipeline
from backend.services.analytics_service import analytics_service
from backend.database import repository


class CameraWorker:

    def __init__(self, camera):
        # camera is a dict from repository.get_camera()
        self.camera_id = camera["id"]
        self.name = camera.get("name", f"cam{self.camera_id}")
        self.source_type = camera.get("source_type", "video")
        self.uri = camera.get("uri", "")
        self.fps_target = max(1, int(camera.get("fps_target", 10)))
        self.models_enabled = camera.get("models_enabled") or {}

        self.cap = None
        self.pipeline = None

        self._thread = None
        self._running = False
        self.paused = False
        self.status = "stopped"
        self.fps = 0.0
        self.error = None

        self._latest_jpeg = None
        self._lock = threading.Lock()

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name=f"cam-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self.cap:
            self.cap.release()
            self.cap = None
        self.status = "stopped"
        repository.set_camera_status(self.camera_id, "stopped")

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    # =====================================================
    # CAPTURE SOURCE
    # =====================================================

    def _open(self):
        try:
            if self.source_type in ("webcam", "usb"):
                src = int(self.uri) if str(self.uri).strip() != "" else 0
                self.cap = cv2.VideoCapture(src)
            elif self.source_type in ("rtsp", "ip", "nvr"):
                if not self.uri:
                    self.error = "No stream URL configured"
                    return False
                self.cap = cv2.VideoCapture(self.uri)
            else:  # video file
                self.cap = cv2.VideoCapture(self.uri)

            if not self.cap or not self.cap.isOpened():
                self.error = f"Cannot open source: {self.uri}"
                return False
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    # =====================================================
    # MAIN LOOP
    # =====================================================

    def _run(self):
        if not self._open():
            self.status = "offline"
            repository.set_camera_status(self.camera_id, "offline")
            repository.add_alert(
                "camera_offline",
                f"{self.name}: {self.error}",
                severity="warning", camera_id=self.camera_id,
            )
            self._running = False
            return

        # build the pipeline (loads models) only once capture is confirmed
        self.pipeline = Pipeline(self.camera_id, self.models_enabled)
        self.status = "processing"
        repository.set_camera_status(self.camera_id, "active")
        # reset any stale metrics for this camera
        analytics_service.reset_camera(self.camera_id)

        target_dt = 1.0 / self.fps_target
        is_file = self.source_type not in ("webcam", "usb", "rtsp", "ip", "nvr")

        while self._running:
            loop_start = time.time()

            if self.paused:
                time.sleep(0.1)
                continue

            ok, frame = self.cap.read()
            if not ok or frame is None:
                if is_file:
                    # loop video files
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                # live source dropped
                self.status = "offline"
                repository.set_camera_status(self.camera_id, "offline")
                time.sleep(0.5)
                continue

            try:
                processed = self.pipeline.process(frame)
                ok2, buf = cv2.imencode(".jpg", processed)
                if ok2:
                    with self._lock:
                        self._latest_jpeg = buf.tobytes()
            except Exception as exc:
                print(f"[CAMERA {self.camera_id} ERROR] {exc}")

            # fps throttle (keeps a steady output cadence)
            elapsed = time.time() - loop_start
            sleep_for = target_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

            # report the ACTUAL output rate (full cycle incl. throttle),
            # smoothed so the displayed number is stable
            cycle = time.time() - loop_start
            inst = 1.0 / cycle if cycle > 0 else self.fps_target
            self.fps = round(0.8 * self.fps + 0.2 * inst, 1) if self.fps else round(inst, 1)

        if self.cap:
            self.cap.release()
            self.cap = None

    # =====================================================
    # READERS
    # =====================================================

    def get_jpeg(self):
        with self._lock:
            return self._latest_jpeg

    def info(self):
        return {
            "camera_id": self.camera_id,
            "running": self._running,
            "status": self.status,
            "paused": self.paused,
            "fps": self.fps,
            "error": self.error,
        }
