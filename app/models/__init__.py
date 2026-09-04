import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Float,
    Integer,
    Boolean,
    Text,
    Enum,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class OutageStatus(str, enum.Enum):
    POSSIBLE = "possible"
    DETECTED = "detected"
    COMMUNITY_CONFIRMED = "community_confirmed"
    OFFICIALLY_CONFIRMED = "officially_confirmed"
    RESTORING = "restoring"
    RESTORED = "restored"
    CLOSED = "closed"
    FALSE_POSITIVE = "false_positive"


class SignalType(str, enum.Enum):
    COMMUNITY_REPORT = "community_report"
    OFFICIAL_ADVISORY = "official_advisory"
    SENSOR = "sensor"
    NETWORK = "network"
    WEATHER = "weather"
    SCRAPER = "scraper"


class SourceType(str, enum.Enum):
    NORECO_II = "noreco_ii"
    NGCP = "ngcp"
    COMMUNITY = "community"
    SENSOR = "sensor"
    NETWORK = "network"
    WEATHER = "weather"


class SourceStatus(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class GeographicArea(Base):
    __tablename__ = "geographic_areas"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    area_type = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("geographic_areas.id"), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    parent = relationship("GeographicArea", remote_side=[id], backref="children")

    __table_args__ = (
        Index("ix_geographic_areas_name", "name"),
        Index("ix_geographic_areas_area_type", "area_type"),
    )


class Outage(Base):
    __tablename__ = "outages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(Enum(OutageStatus), nullable=False, default=OutageStatus.POSSIBLE)
    confidence = Column(Float, nullable=False, default=0.0)
    report_count = Column(Integer, nullable=False, default=0)
    cause = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    first_signal_at = Column(DateTime, nullable=True)
    detected_at = Column(DateTime, nullable=True)
    official_confirmed_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    estimated_restore_at = Column(DateTime, nullable=True)
    restored_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    areas = relationship("OutageArea", back_populates="outage", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="outage", cascade="all, delete-orphan")
    reports = relationship("CommunityReport", back_populates="outage")
    official_advisories = relationship("OfficialAdvisory", back_populates="outage")
    publication_events = relationship("PublicationEvent", back_populates="outage")

    __table_args__ = (
        Index("ix_outages_status", "status"),
        Index("ix_outages_created_at", "created_at"),
        Index("ix_outages_active", "status", "created_at"),
    )


class OutageArea(Base):
    __tablename__ = "outage_areas"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    outage_id = Column(String, ForeignKey("outages.id"), nullable=False)
    area_id = Column(String, ForeignKey("geographic_areas.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    outage = relationship("Outage", back_populates="areas")
    area = relationship("GeographicArea")

    __table_args__ = (
        Index("ix_outage_areas_outage_id", "outage_id"),
        Index("ix_outage_areas_area_id", "area_id"),
    )


class Signal(Base):
    __tablename__ = "signals"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    outage_id = Column(String, ForeignKey("outages.id"), nullable=True)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    signal_type = Column(Enum(SignalType), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    area_id = Column(String, ForeignKey("geographic_areas.id"), nullable=True)
    status = Column(String, nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    metadata_json = Column(Text, nullable=True)
    processed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    outage = relationship("Outage", back_populates="signals")
    source = relationship("Source")
    area = relationship("GeographicArea")

    __table_args__ = (
        Index("ix_signals_outage_id", "outage_id"),
        Index("ix_signals_timestamp", "timestamp"),
        Index("ix_signals_processed", "processed"),
    )


class CommunityReport(Base):
    __tablename__ = "community_reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    outage_id = Column(String, ForeignKey("outages.id"), nullable=True)
    session_id = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    area_id = Column(String, ForeignKey("geographic_areas.id"), nullable=True)
    power_status = Column(String, nullable=False)
    municipality = Column(String, nullable=True)
    barangay = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    device_info = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    outage = relationship("Outage", back_populates="reports")
    area = relationship("GeographicArea")

    __table_args__ = (
        Index("ix_community_reports_outage_id", "outage_id"),
        Index("ix_community_reports_timestamp", "timestamp"),
        Index("ix_community_reports_session_id", "session_id"),
    )


class Source(Base):
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True)
    source_type = Column(Enum(SourceType), nullable=False)
    reliability = Column(Float, nullable=False, default=0.5)
    status = Column(Enum(SourceStatus), nullable=False, default=SourceStatus.UNKNOWN)
    last_seen = Column(DateTime, nullable=True)
    last_success = Column(DateTime, nullable=True)
    last_failure = Column(DateTime, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class OfficialAdvisory(Base):
    __tablename__ = "official_advisories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    outage_id = Column(String, ForeignKey("outages.id"), nullable=False)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    advisory_type = Column(String, nullable=False)
    title = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    url = Column(String, nullable=True)
    published_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    outage = relationship("Outage", back_populates="official_advisories")
    source = relationship("Source")

    __table_args__ = (
        Index("ix_official_advisories_outage_id", "outage_id"),
        Index("ix_official_advisories_published_at", "published_at"),
    )


class PublicationEvent(Base):
    __tablename__ = "publication_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    outage_id = Column(String, ForeignKey("outages.id"), nullable=False)
    publisher_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    channel = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    external_id = Column(String, nullable=True)
    url = Column(String, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=1)
    last_error = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    outage = relationship("Outage", back_populates="publication_events")

    __table_args__ = (
        Index("ix_publication_events_outage_id", "outage_id"),
        Index("ix_publication_events_status", "status"),
    )


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    outage_id = Column(String, ForeignKey("outages.id"), nullable=True)
    source = Column(String, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_system_events_event_type", "event_type"),
        Index("ix_system_events_created_at", "created_at"),
    )


class SensorNode(Base):
    __tablename__ = "sensor_nodes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True)
    area_id = Column(String, ForeignKey("geographic_areas.id"), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    last_heartbeat = Column(DateTime, nullable=True)
    last_power_status = Column(String, nullable=True)
    firmware_version = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    area = relationship("GeographicArea")
