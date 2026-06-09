"""
=====================================================
Repository — scoped-session CRUD for the new schema
=====================================================

All functions use session_scope() (thread-safe) and return
plain dicts / ids so callers never touch detached ORM objects.
Used by services and routes across phases 2+.
"""

from datetime import datetime, timedelta

from collections import Counter, defaultdict

from backend.database.db import session_scope
from backend.database.models import (
    Store, Camera, Zone, Customer, CustomerVisit, ZoneVisit,
    JourneyStep, DemographicSample, MovementPoint, QueueEvent,
    AnalyticsSnapshot, Alert, Setting,
)


# =====================================================
# SERIALIZERS
# =====================================================

def camera_to_dict(c):
    return {
        "id": c.id, "store_id": c.store_id, "name": c.name,
        "source_type": c.source_type, "uri": c.uri, "location": c.location,
        "resolution": c.resolution, "fps_target": c.fps_target,
        "status": c.status, "models_enabled": c.models_enabled or {},
    }


def zone_to_dict(z):
    return {
        "id": z.id, "camera_id": z.camera_id, "name": z.name,
        "shape": z.shape, "points": z.points or [], "color": z.color,
        "kind": z.kind,
    }


# =====================================================
# STORES
# =====================================================

def list_stores():
    with session_scope() as db:
        return [{"id": s.id, "name": s.name, "location": s.location}
                for s in db.query(Store).all()]


# =====================================================
# CAMERAS
# =====================================================

def list_cameras(store_id=None):
    with session_scope() as db:
        q = db.query(Camera)
        if store_id:
            q = q.filter_by(store_id=store_id)
        return [camera_to_dict(c) for c in q.order_by(Camera.id).all()]


def get_camera(camera_id):
    with session_scope() as db:
        c = db.get(Camera, camera_id)
        return camera_to_dict(c) if c else None


def create_camera(data):
    with session_scope() as db:
        c = Camera(
            store_id=data.get("store_id", 1),
            name=data["name"],
            source_type=data.get("source_type", "video"),
            uri=data.get("uri", ""),
            location=data.get("location", ""),
            resolution=data.get("resolution", "1280x720"),
            fps_target=int(data.get("fps_target", 10)),
            status="stopped",
            models_enabled=data.get("models_enabled") or {
                "detection": True, "tracking": True, "reid": True,
                "demographics": True, "heatmap": True, "zones": True
            },
        )
        db.add(c)
        db.flush()
        return camera_to_dict(c)


def update_camera(camera_id, data):
    with session_scope() as db:
        c = db.get(Camera, camera_id)
        if not c:
            return None
        for field in ("name", "source_type", "uri", "location",
                      "resolution", "fps_target", "status", "models_enabled"):
            if field in data and data[field] is not None:
                setattr(c, field, data[field])
        db.flush()
        return camera_to_dict(c)


def set_camera_status(camera_id, status):
    with session_scope() as db:
        c = db.get(Camera, camera_id)
        if c:
            c.status = status


def delete_camera(camera_id):
    with session_scope() as db:
        c = db.get(Camera, camera_id)
        if c:
            db.delete(c)
            return True
        return False


# =====================================================
# ZONES
# =====================================================

def list_zones(camera_id):
    with session_scope() as db:
        return [zone_to_dict(z) for z in
                db.query(Zone).filter_by(camera_id=camera_id).order_by(Zone.id).all()]


def create_zone(camera_id, data):
    with session_scope() as db:
        z = Zone(
            camera_id=camera_id,
            name=data["name"],
            shape=data.get("shape", "polygon"),
            points=data.get("points", []),
            color=data.get("color", "#00ff99"),
            kind=data.get("kind", "generic"),
        )
        db.add(z)
        db.flush()
        return zone_to_dict(z)


def update_zone(zone_id, data):
    with session_scope() as db:
        z = db.get(Zone, zone_id)
        if not z:
            return None
        for field in ("name", "shape", "points", "color", "kind"):
            if field in data and data[field] is not None:
                setattr(z, field, data[field])
        db.flush()
        return zone_to_dict(z)


def delete_zone(zone_id):
    with session_scope() as db:
        z = db.get(Zone, zone_id)
        if z:
            db.delete(z)
            return True
        return False


# =====================================================
# ZONE ANALYTICS (from ZoneVisit)
# =====================================================

def zone_metrics(camera_id):
    """Per-zone aggregates: visitors, unique, avg/max dwell, revisits, entries."""
    with session_scope() as db:
        zones = db.query(Zone).filter_by(camera_id=camera_id).all()
        zname = {z.id: z.name for z in zones}

        visits = (db.query(ZoneVisit)
                  .filter_by(camera_id=camera_id).all())

        agg = {z.id: {
            "zone_id": z.id, "name": z.name, "kind": z.kind,
            "total_visits": 0, "unique": set(), "dwell_sum": 0.0,
            "max_dwell": 0.0, "revisits": 0, "entries": 0,
        } for z in zones}

        for v in visits:
            a = agg.get(v.zone_id)
            if not a:
                continue
            a["total_visits"] += 1
            a["entries"] += 1
            a["unique"].add(v.customer_id)
            a["dwell_sum"] += (v.dwell_seconds or 0)
            a["max_dwell"] = max(a["max_dwell"], v.dwell_seconds or 0)
            if (v.revisit_index or 0) > 1:
                a["revisits"] += 1

        out = []
        for a in agg.values():
            n = a["total_visits"]
            out.append({
                "zone_id": a["zone_id"], "name": a["name"], "kind": a["kind"],
                "total_visits": n,
                "unique_visitors": len(a["unique"]),
                "avg_dwell": round(a["dwell_sum"] / n, 1) if n else 0.0,
                "max_dwell": round(a["max_dwell"], 1),
                "revisits": a["revisits"],
                "entries": a["entries"],
            })
        out.sort(key=lambda r: r["total_visits"], reverse=True)
        return out


def zone_hourly_activity(camera_id):
    """Zone visits bucketed by hour-of-day (0-23)."""
    with session_scope() as db:
        rows = (db.query(ZoneVisit)
                .filter_by(camera_id=camera_id).all())
        hours = [0] * 24
        for v in rows:
            if v.entry_time:
                hours[v.entry_time.hour] += 1
        return {"labels": [f"{h:02d}:00" for h in range(24)], "visits": hours}


# =====================================================
# CUSTOMER VISIT LIFECYCLE
# =====================================================

def open_customer_visit(reid_id, camera_id, age=None, gender=None, store_id=1):
    """Upsert the Customer (by reid id) and open a new CustomerVisit.
    Returns the new visit id."""
    with session_scope() as db:
        now = datetime.utcnow()
        cust = db.get(Customer, reid_id)
        if cust is None:
            cust = Customer(
                id=reid_id, store_id=store_id,
                first_seen=now, last_seen=now, visit_count=1,
                camera_history=[camera_id],
                est_age=age, est_gender=gender,
            )
            db.add(cust)
        else:
            cust.visit_count = (cust.visit_count or 0) + 1
            cust.last_seen = now
            hist = list(cust.camera_history or [])
            if camera_id not in hist:
                hist.append(camera_id)
                cust.camera_history = hist
            if age is not None and cust.est_age is None:
                cust.est_age = age
            if gender and not cust.est_gender:
                cust.est_gender = gender

        visit = CustomerVisit(
            customer_id=reid_id, camera_id=camera_id, entry_time=now,
        )
        db.add(visit)
        db.flush()
        return visit.id


def close_customer_visit(visit_id, dwell_seconds):
    with session_scope() as db:
        v = db.get(CustomerVisit, visit_id)
        if not v:
            return
        v.exit_time = datetime.utcnow()
        v.dwell_seconds = round(dwell_seconds, 1)
        cust = db.get(Customer, v.customer_id)
        if cust:
            cust.last_seen = v.exit_time


# =====================================================
# CUSTOMER READS
# =====================================================

def list_customers(start=None, end=None, camera_id=None, limit=200):
    with session_scope() as db:
        q = db.query(Customer)
        if start is not None:
            q = q.filter(Customer.last_seen >= start)
        if end is not None:
            q = q.filter(Customer.last_seen <= end)
        custs = q.order_by(Customer.last_seen.desc()).limit(limit).all()
        ids = [c.id for c in custs]
        if not ids:
            return []

        # visits aggregate per customer
        visits = (db.query(CustomerVisit)
                  .filter(CustomerVisit.customer_id.in_(ids)).all())
        vagg = defaultdict(lambda: {"entry": None, "exit": None, "dwell": 0.0})
        for v in visits:
            if camera_id and v.camera_id != camera_id:
                continue
            a = vagg[v.customer_id]
            if a["entry"] is None or (v.entry_time and v.entry_time < a["entry"]):
                a["entry"] = v.entry_time
            if v.exit_time and (a["exit"] is None or v.exit_time > a["exit"]):
                a["exit"] = v.exit_time
            a["dwell"] += (v.dwell_seconds or 0)

        # zones visited per customer
        zvisits = (db.query(ZoneVisit)
                   .filter(ZoneVisit.customer_id.in_(ids)).all())
        zname = {z.id: z.name for z in db.query(Zone).all()}
        zones_by_cust = defaultdict(set)
        for zv in zvisits:
            n = zname.get(zv.zone_id)
            if n:
                zones_by_cust[zv.customer_id].add(n)

        out = []
        for c in custs:
            a = vagg.get(c.id, {})
            out.append({
                "id": c.id,
                "entry": a.get("entry").strftime("%Y-%m-%d %H:%M:%S") if a.get("entry") else "—",
                "exit": a.get("exit").strftime("%Y-%m-%d %H:%M:%S") if a.get("exit") else "active",
                "dwell": round(a.get("dwell", 0.0), 1),
                "zones": sorted(zones_by_cust.get(c.id, [])),
                "gender": c.est_gender or "—",
                "age": c.est_age if c.est_age is not None else "—",
                "visit_count": c.visit_count or 1,
            })
        return out


def get_customer_detail(customer_id):
    with session_scope() as db:
        c = db.get(Customer, customer_id)
        if not c:
            return None
        zname = {z.id: z.name for z in db.query(Zone).all()}

        visits = (db.query(CustomerVisit)
                  .filter_by(customer_id=customer_id)
                  .order_by(CustomerVisit.entry_time.asc()).all())
        zvisits = (db.query(ZoneVisit)
                   .filter_by(customer_id=customer_id)
                   .order_by(ZoneVisit.entry_time.asc()).all())

        # journey path (collapse consecutive repeats)
        path = []
        for zv in zvisits:
            n = zname.get(zv.zone_id)
            if n and (not path or path[-1] != n):
                path.append(n)

        return {
            "id": c.id,
            "first_seen": c.first_seen.strftime("%Y-%m-%d %H:%M:%S") if c.first_seen else "—",
            "last_seen": c.last_seen.strftime("%Y-%m-%d %H:%M:%S") if c.last_seen else "—",
            "visit_count": c.visit_count or 1,
            "gender": c.est_gender or "—",
            "age": c.est_age if c.est_age is not None else "—",
            "cameras": c.camera_history or [],
            "journey": path,
            "visits": [{
                "camera_id": v.camera_id,
                "entry": v.entry_time.strftime("%H:%M:%S") if v.entry_time else "—",
                "exit": v.exit_time.strftime("%H:%M:%S") if v.exit_time else "active",
                "dwell": v.dwell_seconds or 0,
            } for v in visits],
            "zone_visits": [{
                "zone": zname.get(zv.zone_id, "?"),
                "dwell": zv.dwell_seconds or 0,
                "revisit": zv.revisit_index or 1,
            } for zv in zvisits],
        }


def recent_avg_dwell(start=None, end=None, limit=500):
    """Average customer visit dwell (seconds) over recent completed visits."""
    with session_scope() as db:
        q = db.query(CustomerVisit).filter(CustomerVisit.dwell_seconds > 0)
        if start is not None:
            q = q.filter(CustomerVisit.entry_time >= start)
        if end is not None:
            q = q.filter(CustomerVisit.entry_time <= end)
        rows = q.order_by(CustomerVisit.entry_time.desc()).limit(limit).all()
        if not rows:
            return 0.0
        return round(sum(r.dwell_seconds or 0 for r in rows) / len(rows), 1)


def customer_demographics(start=None, end=None):
    with session_scope() as db:
        q = db.query(Customer)
        if start is not None:
            q = q.filter(Customer.last_seen >= start)
        if end is not None:
            q = q.filter(Customer.last_seen <= end)
        custs = q.all()

        male = sum(1 for c in custs if c.est_gender == "Man")
        female = sum(1 for c in custs if c.est_gender == "Woman")

        buckets = {"0-17": 0, "18-25": 0, "26-35": 0, "36-50": 0, "51+": 0}
        for c in custs:
            if c.est_age is None:
                continue
            a = c.est_age
            if a <= 17: buckets["0-17"] += 1
            elif a <= 25: buckets["18-25"] += 1
            elif a <= 35: buckets["26-35"] += 1
            elif a <= 50: buckets["36-50"] += 1
            else: buckets["51+"] += 1

        return {
            "total": len(custs),
            "male": male, "female": female,
            "age_labels": list(buckets.keys()),
            "age_values": list(buckets.values()),
        }


def returning_customers(start=None, end=None, limit=50):
    with session_scope() as db:
        q = db.query(Customer).filter(Customer.visit_count > 1)
        if start is not None:
            q = q.filter(Customer.last_seen >= start)
        custs = q.order_by(Customer.visit_count.desc()).limit(limit).all()
        ids = [c.id for c in custs]

        avg_stay = {}
        if ids:
            visits = (db.query(CustomerVisit)
                      .filter(CustomerVisit.customer_id.in_(ids)).all())
            agg = defaultdict(lambda: [0.0, 0])
            for v in visits:
                if v.dwell_seconds:
                    agg[v.customer_id][0] += v.dwell_seconds
                    agg[v.customer_id][1] += 1
            for cid, (s, n) in agg.items():
                avg_stay[cid] = round(s / n, 1) if n else 0.0

        return {
            "count": len(custs),
            "customers": [{
                "id": c.id,
                "visits": c.visit_count,
                "gender": c.est_gender or "—",
                "age": c.est_age if c.est_age is not None else "—",
                "avg_stay": avg_stay.get(c.id, 0.0),
                "last_seen": c.last_seen.strftime("%Y-%m-%d %H:%M:%S") if c.last_seen else "—",
            } for c in custs],
        }


def movement_points(camera_id, start=None, end=None, limit=5000):
    """Return movement points for a camera (optionally within a time range)."""
    with session_scope() as db:
        q = db.query(MovementPoint).filter_by(camera_id=camera_id)
        if start is not None:
            q = q.filter(MovementPoint.ts >= start)
        if end is not None:
            q = q.filter(MovementPoint.ts <= end)
        rows = q.order_by(MovementPoint.ts.desc()).limit(limit).all()
        return [{"x": r.x, "y": r.y, "ts": r.ts} for r in rows]


def zone_journeys(camera_id, top=6):
    """Common zone paths, least-visited zones, and a simple funnel."""
    with session_scope() as db:
        zones = db.query(Zone).filter_by(camera_id=camera_id).all()
        zname = {z.id: z.name for z in zones}

        visits = (db.query(ZoneVisit)
                  .filter_by(camera_id=camera_id)
                  .order_by(ZoneVisit.entry_time.asc()).all())

        # build ordered path per customer (collapse consecutive repeats)
        seq = defaultdict(list)
        for v in visits:
            name = zname.get(v.zone_id)
            if not name:
                continue
            if not seq[v.customer_id] or seq[v.customer_id][-1] != name:
                seq[v.customer_id].append(name)

        # common paths (length >= 2)
        path_counter = Counter()
        for cust, path in seq.items():
            if len(path) >= 2:
                path_counter[" → ".join(path)] += 1

        common = [{"path": p, "count": c}
                  for p, c in path_counter.most_common(top)]

        # least-visited zones
        visit_count = Counter()
        for v in visits:
            n = zname.get(v.zone_id)
            if n:
                visit_count[n] += 1
        least = sorted(
            ({"zone": z.name, "count": visit_count.get(z.name, 0)} for z in zones),
            key=lambda r: r["count"]
        )[:3]

        # funnel: entrance-kind -> any -> checkout-kind
        entrance = {z.name for z in zones if z.kind == "entrance"}
        checkout = {z.name for z in zones if z.kind == "checkout"}
        reached_entrance = reached_any = reached_checkout = 0
        for cust, path in seq.items():
            s = set(path)
            if entrance & s:
                reached_entrance += 1
            if len(path) >= 2:
                reached_any += 1
            if checkout & s:
                reached_checkout += 1

        funnel = [
            {"stage": "Entered Store", "count": reached_entrance or len(seq)},
            {"stage": "Browsed Zones", "count": reached_any},
            {"stage": "Reached Checkout", "count": reached_checkout},
        ]

        return {"common_paths": common, "least_visited": least, "funnel": funnel}


# =====================================================
# ALERTS
# =====================================================

def add_alert(type_, message, severity="info", camera_id=None, store_id=1):
    with session_scope() as db:
        a = Alert(type=type_, message=message, severity=severity,
                  camera_id=camera_id, store_id=store_id)
        db.add(a)
        db.flush()
        return a.id


def list_alerts(limit=50, only_unack=False):
    with session_scope() as db:
        q = db.query(Alert)
        if only_unack:
            q = q.filter_by(acknowledged=False)
        rows = q.order_by(Alert.ts.desc()).limit(limit).all()
        return [{
            "id": a.id, "type": a.type, "severity": a.severity,
            "message": a.message, "camera_id": a.camera_id,
            "ts": a.ts.strftime("%Y-%m-%d %H:%M:%S"),
            "acknowledged": a.acknowledged,
        } for a in rows]


def ack_alert(alert_id):
    with session_scope() as db:
        a = db.get(Alert, alert_id)
        if a:
            a.acknowledged = True
            return True
        return False


# =====================================================
# SETTINGS
# =====================================================

def get_setting(key, default=None, scope="global", camera_id=None):
    with session_scope() as db:
        s = (db.query(Setting)
             .filter_by(key=key, scope=scope, camera_id=camera_id).first())
        return s.value if s else default


def set_setting(key, value, scope="global", camera_id=None):
    with session_scope() as db:
        s = (db.query(Setting)
             .filter_by(key=key, scope=scope, camera_id=camera_id).first())
        if s:
            s.value = value
        else:
            db.add(Setting(key=key, value=value, scope=scope, camera_id=camera_id))


def all_settings():
    with session_scope() as db:
        return [{"scope": s.scope, "camera_id": s.camera_id,
                 "key": s.key, "value": s.value}
                for s in db.query(Setting).all()]


# =====================================================
# ANALYTICS SNAPSHOTS (rollup reads)
# =====================================================

def add_snapshot(metrics, camera_id=None, store_id=1):
    with session_scope() as db:
        db.add(AnalyticsSnapshot(
            store_id=store_id, camera_id=camera_id,
            occupancy=metrics.get("occupancy", 0),
            entries=metrics.get("entries", 0),
            exits=metrics.get("exits", 0),
            unique_customers=metrics.get("total_tracks", 0),
            male=metrics.get("male_count", 0),
            female=metrics.get("female_count", 0),
            avg_dwell=metrics.get("avg_dwell", 0.0),
            queue_len=metrics.get("queue_length", 0),
            avg_wait=metrics.get("average_wait", 0.0),
        ))


def snapshots_in_range(start=None, end=None, camera_id=None, limit=5000):
    with session_scope() as db:
        q = db.query(AnalyticsSnapshot)
        if camera_id:
            q = q.filter_by(camera_id=camera_id)
        if start:
            q = q.filter(AnalyticsSnapshot.ts >= start)
        if end:
            q = q.filter(AnalyticsSnapshot.ts <= end)
        rows = q.order_by(AnalyticsSnapshot.ts.asc()).limit(limit).all()
        return [{
            "ts": r.ts.strftime("%Y-%m-%d %H:%M:%S"),
            "occupancy": r.occupancy, "entries": r.entries, "exits": r.exits,
            "unique_customers": r.unique_customers,
            "male": r.male, "female": r.female,
            "avg_dwell": r.avg_dwell, "queue_len": r.queue_len,
            "avg_wait": r.avg_wait,
        } for r in rows]
