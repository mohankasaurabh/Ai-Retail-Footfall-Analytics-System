"""
=====================================================
Database models
=====================================================

Enterprise schema for the modular platform. All analytics
tables carry store_id / camera_id so data is scoped per
store and per camera (single-tenant today; multi-tenant ready).

Legacy tables (AnalyticsLog, MovementLog) are retained for
back-compat during the phased migration.
"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime, ForeignKey, JSON, Text
)
from sqlalchemy.orm import relationship

from backend.database.db import Base


# =====================================================
# TENANCY
# =====================================================

class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, default="Default Store")
    location = Column(String(200), default="")
    timezone = Column(String(64), default="UTC")
    created_at = Column(DateTime, default=datetime.utcnow)

    cameras = relationship("Camera", back_populates="store")


class User(Base):
    """Stub — present in schema but not enforced yet (single implicit admin)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(256), default="")
    role = Column(String(20), default="admin")  # admin | viewer
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# =====================================================
# MEDIA SOURCES
# =====================================================

class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), default=1)
    name = Column(String(120), nullable=False)
    source_type = Column(String(20), default="video")  # webcam|video|rtsp|ip|nvr
    uri = Column(Text, default="")                      # path / index / rtsp url
    location = Column(String(200), default="")
    resolution = Column(String(20), default="1280x720")
    fps_target = Column(Integer, default=12)
    status = Column(String(20), default="stopped")      # active|offline|processing|stopped
    models_enabled = Column(JSON, default=lambda: {
        "detection": True, "tracking": True, "reid": True,
        "demographics": True, "heatmap": True, "zones": True
    })
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store", back_populates="cameras")
    zones = relationship("Zone", back_populates="camera",
                         cascade="all, delete-orphan")


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), index=True)
    name = Column(String(120), nullable=False)
    shape = Column(String(20), default="polygon")        # polygon | rect
    points = Column(JSON, default=list)                  # [[x,y], ...]
    color = Column(String(20), default="#00ff99")
    kind = Column(String(20), default="generic")         # generic|entrance|checkout|queue
    created_at = Column(DateTime, default=datetime.utcnow)

    camera = relationship("Camera", back_populates="zones")


# =====================================================
# CUSTOMERS & IDENTITY
# =====================================================

class Customer(Base):
    """Persistent identity — id mirrors the global ReID identity id."""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), default=1)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    visit_count = Column(Integer, default=1)
    camera_history = Column(JSON, default=list)          # [camera_id, ...]
    est_age = Column(Integer, nullable=True)
    est_gender = Column(String(10), nullable=True)       # Man | Woman

    visits = relationship("CustomerVisit", back_populates="customer",
                          cascade="all, delete-orphan")


class CustomerVisit(Base):
    __tablename__ = "customer_visits"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), index=True)
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    dwell_seconds = Column(Float, default=0.0)

    customer = relationship("Customer", back_populates="visits")
    steps = relationship("JourneyStep", back_populates="visit",
                         cascade="all, delete-orphan")


class ZoneVisit(Base):
    __tablename__ = "zone_visits"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), index=True)
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    dwell_seconds = Column(Float, default=0.0)
    revisit_index = Column(Integer, default=0)


class JourneyStep(Base):
    __tablename__ = "journey_steps"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("customer_visits.id"), index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    zone_name = Column(String(120), default="")
    seq_index = Column(Integer, default=0)
    entered_at = Column(DateTime, default=datetime.utcnow)

    visit = relationship("CustomerVisit", back_populates="steps")


class DemographicSample(Base):
    __tablename__ = "demographic_samples"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), index=True)
    age = Column(Integer)
    gender = Column(String(10))
    confidence = Column(Float, default=0.0)
    ts = Column(DateTime, default=datetime.utcnow)


# =====================================================
# MOVEMENT / QUEUE / ROLLUPS
# =====================================================

class MovementPoint(Base):
    __tablename__ = "movement_points"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    x = Column(Float)
    y = Column(Float)
    ts = Column(DateTime, default=datetime.utcnow)


class QueueEvent(Base):
    __tablename__ = "queue_events"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    customer_id = Column(Integer, nullable=True)
    enter_ts = Column(DateTime, default=datetime.utcnow)
    exit_ts = Column(DateTime, nullable=True)
    wait_seconds = Column(Float, default=0.0)


class AnalyticsSnapshot(Base):
    """Periodic rollup — supersedes AnalyticsLog."""
    __tablename__ = "analytics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), default=1)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True, index=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    occupancy = Column(Integer, default=0)
    entries = Column(Integer, default=0)
    exits = Column(Integer, default=0)
    unique_customers = Column(Integer, default=0)
    male = Column(Integer, default=0)
    female = Column(Integer, default=0)
    avg_dwell = Column(Float, default=0.0)
    queue_len = Column(Integer, default=0)
    avg_wait = Column(Float, default=0.0)


# =====================================================
# ALERTS / SETTINGS
# =====================================================

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), default=1)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    type = Column(String(40))          # camera_offline|low_fps|ai_error|occupancy|queue
    severity = Column(String(20), default="info")  # info|warning|critical
    message = Column(Text, default="")
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    acknowledged = Column(Boolean, default=False)


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(20), default="global")   # global | camera
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    key = Column(String(80), index=True)
    value = Column(JSON)


class HeatmapBin(Base):
    """Optional pre-binned historical heatmap aggregation."""
    __tablename__ = "heatmap_bins"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), index=True)
    gx = Column(Integer)
    gy = Column(Integer)
    weight = Column(Float, default=0.0)
    bucket_ts = Column(DateTime, default=datetime.utcnow, index=True)


# =====================================================
# LEGACY (retained during phased migration)
# =====================================================

class AnalyticsLog(Base):
    __tablename__ = "analytics_logs"

    id = Column(Integer, primary_key=True, index=True)
    occupancy = Column(Integer)
    entries = Column(Integer)
    exits = Column(Integer)
    active_customers = Column(Integer)
    zone_occupancy = Column(Integer)
    total_tracks = Column(Integer)
    reid_identities = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)


class MovementLog(Base):
    __tablename__ = "movement_logs"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer)
    x = Column(Float)
    y = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
