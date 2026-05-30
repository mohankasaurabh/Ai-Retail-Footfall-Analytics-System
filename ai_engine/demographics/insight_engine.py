"""
=====================================================
InsightFace engine — RetinaFace detection + gender/age
=====================================================

Replaces the old Haar-cascade + DeepFace path. InsightFace's
buffalo_l pack provides a far stronger face detector (RetinaFace)
plus a gender/age model, which works much better on distant /
angled CCTV faces.

A single FaceAnalysis app is shared across all camera workers
(lazy-initialised, thread-locked) to avoid loading the model N
times. Inference is guarded by a lock; demographics is throttled
in the pipeline so this is not a hot path.
"""

import threading

import numpy as np

_app = None
_init_lock = threading.Lock()
_infer_lock = threading.Lock()


def get_face_app():
    """Lazily build the shared InsightFace FaceAnalysis app (CPU)."""
    global _app
    if _app is None:
        with _init_lock:
            if _app is None:
                from insightface.app import FaceAnalysis
                app = FaceAnalysis(
                    name="buffalo_l",
                    allowed_modules=["detection", "genderage"],
                    providers=["CPUExecutionProvider"],
                )
                # ctx_id=-1 -> CPU. det_size 640 keeps the demographics pass
                # fast enough to avoid stuttering the video; det_thresh=0.5
                # limits poster/false positives.
                app.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.5)
                _app = app
                print("[INSIGHTFACE] model ready (buffalo_l, CPU)")
    return _app


def detect_faces(frame):
    """Return detected faces with gender/age.

    [{ "bbox": (x1,y1,x2,y2), "gender": "Man"|"Woman",
       "age": int, "score": float }]
    """
    if frame is None or frame.size == 0:
        return []
    try:
        app = get_face_app()
        with _infer_lock:
            faces = app.get(frame)
    except Exception as exc:
        print(f"[INSIGHTFACE ERROR] {exc}")
        return []

    out = []
    for f in faces:
        try:
            x1, y1, x2, y2 = [int(v) for v in f.bbox]
        except Exception:
            continue
        # insightface: gender 1 = male, 0 = female
        gender = "Man" if int(getattr(f, "gender", 0)) == 1 else "Woman"
        out.append({
            "bbox": (x1, y1, x2, y2),
            "gender": gender,
            "age": int(getattr(f, "age", 0)),
            "score": float(getattr(f, "det_score", 0.0)),
        })
    return out
