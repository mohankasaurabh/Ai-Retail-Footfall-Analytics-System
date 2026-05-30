"""
=====================================================
Demographics Voter — per-ReID multi-frame voting
=====================================================

A single face read is noisy (angle, blur, motion). Since every
person already has a persistent ReID id, we accumulate gender
votes (weighted by face-detection confidence) and age samples
across that person's whole journey, and return a stable label.

    voter.update(reid_id, "Man", score=0.82, age=31)
    voter.get(reid_id) -> {"gender": "Man", "age": 30, "confidence": 0.78}
"""


class DemographicsVoter:

    def __init__(self):
        # reid_id -> {"m": float, "f": float, "age_sum": float, "age_n": int}
        self.votes = {}

    def update(self, reid_id, gender, score=1.0, age=None):
        if reid_id is None:
            return
        d = self.votes.setdefault(
            reid_id, {"m": 0.0, "f": 0.0, "age_sum": 0.0, "age_n": 0}
        )
        w = max(0.1, float(score))   # weight clearer faces more
        if gender == "Man":
            d["m"] += w
        else:
            d["f"] += w
        if age is not None:
            d["age_sum"] += age
            d["age_n"] += 1

    def get(self, reid_id):
        d = self.votes.get(reid_id)
        if not d:
            return None
        total = d["m"] + d["f"]
        if total <= 0:
            return None
        gender = "Man" if d["m"] >= d["f"] else "Woman"
        confidence = round(max(d["m"], d["f"]) / total, 2)
        age = int(d["age_sum"] / d["age_n"]) if d["age_n"] else None
        return {"gender": gender, "age": age, "confidence": confidence}
