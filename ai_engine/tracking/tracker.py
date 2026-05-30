from ultralytics import YOLO
import torch


class CustomerTracker:

    def __init__(self):

        self.device = "mps" if torch.backends.mps.is_available() else "cpu"

        print(f"[INFO] Tracking Device: {self.device}")

        self.model = YOLO("yolo11s.pt")

        self.model.to(self.device)

    def track(self, frame):

        results = self.model.track(
            frame,
            persist=True,
            tracker="ai_engine/tracking/bytetrack_config.yaml",
            classes=[0],
            conf=0.4,
            imgsz=960,        # smaller -> faster/smoother (was 1280)
            verbose=False
        )

        tracked_objects = []

        for result in results:

            boxes = result.boxes

            if boxes.id is None:
                continue

            for box, track_id in zip(boxes.xyxy, boxes.id):

                x1, y1, x2, y2 = map(int, box)

                tracked_objects.append({
                    "track_id": int(track_id),
                    "bbox": [x1, y1, x2, y2]
                })

        return tracked_objects