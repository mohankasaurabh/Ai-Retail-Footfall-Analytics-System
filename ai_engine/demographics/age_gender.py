"""
=====================================================
Demographics Analyzer (InsightFace-powered)
=====================================================

Uses InsightFace (RetinaFace detection + gender/age) instead of
the old Haar + DeepFace path.

- analyze_frame(frame): detect ALL faces in a frame in one pass
  (efficient for the per-camera pipeline, which then maps each
  face to a tracked person).
- analyze_person(frame, bbox, track_id): back-compat single-person
  ROI analysis (used by the legacy frame_processor).
"""

from ai_engine.demographics.insight_engine import detect_faces


class DemographicsAnalyzer:

    def __init__(self):
        # InsightFace app is a lazy shared singleton (insight_engine)
        pass

    # =====================================
    # WHOLE-FRAME (preferred)
    # =====================================

    def analyze_frame(self, frame):
        """Return all detected faces: [{bbox(x1,y1,x2,y2), gender, age, score}]."""
        return detect_faces(frame)

    # =====================================
    # SINGLE PERSON ROI (back-compat)
    # =====================================

    def analyze_person(self, frame, bbox, track_id):
        x1, y1, x2, y2 = bbox
        person_crop = frame[y1:y2, x1:x2]
        if person_crop.size == 0:
            return None

        faces = detect_faces(person_crop)
        if not faces:
            return None

        # strongest detection
        f = max(faces, key=lambda d: d["score"])
        fx1, fy1, fx2, fy2 = f["bbox"]
        return {
            "track_id": track_id,
            "age": f["age"],
            "gender": f["gender"],
            "score": f["score"],
            # convert ROI coords to full-frame (x, y, w, h)
            "bbox": (x1 + fx1, y1 + fy1, fx2 - fx1, fy2 - fy1),
        }
