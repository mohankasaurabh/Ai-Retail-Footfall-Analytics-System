"""
=====================================================
Media Source Routes
=====================================================

CRUD for cameras/sources + runtime control (start/stop) +
per-camera MJPEG stream and snapshot. Sources are persisted
in the DB; MediaSourceService manages the live workers.
"""

import os

from flask import Blueprint, request, jsonify, Response
from werkzeug.utils import secure_filename

from backend.services.media_source_service import media_source_service
from backend.database import repository


source_bp = Blueprint("sources", __name__)

UPLOAD_DIR = "data/videos"
ALLOWED_VIDEO = {".mp4", ".avi", ".mov", ".mkv"}


# =====================================================
# VIDEO UPLOAD (MP4 / AVI / MOV)
# =====================================================

@source_bp.route("/api/sources/upload", methods=["POST"])
def upload_video():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"success": False, "message": "no file"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_VIDEO:
        return jsonify({
            "success": False,
            "message": f"unsupported type {ext}",
        }), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = secure_filename(f.filename)
    path = os.path.join(UPLOAD_DIR, filename)
    f.save(path)
    return jsonify({"success": True, "path": path, "filename": filename})


# =====================================================
# CRUD + STATUS
# =====================================================

@source_bp.route("/api/sources", methods=["GET"])
def list_sources():
    return jsonify(media_source_service.status_all())


@source_bp.route("/api/sources", methods=["POST"])
def create_source():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("name"):
        return jsonify({"success": False, "message": "name required"}), 400
    cam = repository.create_camera(data)
    return jsonify({"success": True, "camera": cam})


@source_bp.route("/api/sources/<int:camera_id>", methods=["GET"])
def get_source(camera_id):
    cam = repository.get_camera(camera_id)
    if not cam:
        return jsonify({"success": False, "message": "not found"}), 404
    return jsonify(cam)


@source_bp.route("/api/sources/<int:camera_id>", methods=["PUT"])
def update_source(camera_id):
    data = request.get_json(force=True, silent=True) or {}
    cam = repository.update_camera(camera_id, data)
    if not cam:
        return jsonify({"success": False, "message": "not found"}), 404
    # if running and source params changed, restart to apply
    if media_source_service.is_running(camera_id):
        media_source_service.stop_camera(camera_id)
        media_source_service.start_camera(camera_id)
    return jsonify({"success": True, "camera": cam})


@source_bp.route("/api/sources/<int:camera_id>", methods=["DELETE"])
def delete_source(camera_id):
    media_source_service.stop_camera(camera_id)
    ok = repository.delete_camera(camera_id)
    return jsonify({"success": ok})


# =====================================================
# RUNTIME CONTROL
# =====================================================

@source_bp.route("/api/sources/<int:camera_id>/start", methods=["POST"])
def start_source(camera_id):
    return jsonify(media_source_service.start_camera(camera_id))


@source_bp.route("/api/sources/<int:camera_id>/stop", methods=["POST"])
def stop_source(camera_id):
    return jsonify(media_source_service.stop_camera(camera_id))


@source_bp.route("/api/sources/<int:camera_id>/metrics", methods=["GET"])
def source_metrics(camera_id):
    return jsonify(media_source_service.get_metrics(camera_id))


# =====================================================
# FRAMES
# =====================================================

@source_bp.route("/video_feed/<int:camera_id>")
def video_feed(camera_id):
    if not media_source_service.is_running(camera_id):
        # auto-start so opening the page just works
        media_source_service.start_camera(camera_id)
    return Response(
        media_source_service.mjpeg_generator(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@source_bp.route("/api/sources/<int:camera_id>/snapshot")
def snapshot(camera_id):
    # clean=1 returns an un-annotated frame (used as the heatmap background)
    if request.args.get("clean") == "1":
        jpeg = media_source_service.get_clean_jpeg(camera_id)
    else:
        jpeg = media_source_service.get_jpeg(camera_id)
    if jpeg is None:
        return jsonify({"success": False, "message": "no frame yet"}), 404
    return Response(jpeg, mimetype="image/jpeg")
