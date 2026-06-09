"""
=====================================================
Reset demo / analytics data
=====================================================

Clears all runtime ANALYTICS data so the platform starts
from clean, realistic numbers — while KEEPING configuration
(stores, users, cameras, zones, settings).

Run:  python -m backend.database.reset_demo
"""

from backend.database.db import engine
import backend.database.models  # noqa: F401  (register models)
from sqlalchemy import text


# tables wiped (runtime analytics) — config tables are preserved
ANALYTICS_TABLES = [
    "movement_points", "movement_logs",
    "zone_visits", "journey_steps",
    "customer_visits", "demographic_samples", "customers",
    "queue_events", "heatmap_bins",
    "analytics_snapshots", "analytics_logs",
    "alerts",
]

PRESERVED = ["stores", "users", "cameras", "zones", "settings"]


def reset_demo():
    with engine.begin() as conn:
        for t in ANALYTICS_TABLES:
            try:
                conn.execute(text(f"DELETE FROM {t}"))
            except Exception as exc:
                print(f"[RESET] skip {t}: {exc}")
        # mark all cameras stopped
        try:
            conn.execute(text("UPDATE cameras SET status='stopped'"))
        except Exception:
            pass
    # reclaim space (SQLite)
    try:
        with engine.begin() as conn:
            conn.execute(text("VACUUM"))
    except Exception:
        pass

    print("[RESET] cleared:", ", ".join(ANALYTICS_TABLES))
    print("[RESET] preserved:", ", ".join(PRESERVED))


if __name__ == "__main__":
    reset_demo()
