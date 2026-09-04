from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class OutageStatusEnum(str, Enum):
    POSSIBLE = "possible"
    DETECTED = "detected"
    COMMUNITY_CONFIRMED = "community_confirmed"
    OFFICIALLY_CONFIRMED = "officially_confirmed"
    RESTORING = "restoring"
    RESTORED = "restored"
    CLOSED = "closed"
    FALSE_POSITIVE = "false_positive"


class SourceTypeEnum(str, Enum):
    NORECO_II = "noreco_ii"
    NGCP = "ngcp"
    COMMUNITY = "community"
    SENSOR = "sensor"
    NETWORK = "network"
    WEATHER = "weather"


class SourceStatusEnum(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SignalTypeEnum(str, Enum):
    COMMUNITY_REPORT = "community_report"
    OFFICIAL_ADVISORY = "official_advisory"
    SENSOR = "sensor"
    NETWORK = "network"
    WEATHER = "weather"
    SCRAPER = "scraper"


class GeographicAreaSchema(BaseModel):
    id: str
    name: str
    area_type: str
    parent_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    metadata_json: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class OutageAreaSchema(BaseModel):
    id: str
    outage_id: str
    area_id: str
    area: Optional[GeographicAreaSchema] = None
    created_at: datetime

    class Config:
        from_attributes = True


class OutageSchema(BaseModel):
    id: str
    status: OutageStatusEnum
    confidence: float
    report_count: int
    cause: Optional[str] = None
    notes: Optional[str] = None
    first_signal_at: Optional[datetime] = None
    detected_at: Optional[datetime] = None
    official_confirmed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    estimated_restore_at: Optional[datetime] = None
    restored_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    areas: List[OutageAreaSchema] = []

    class Config:
        from_attributes = True


class SignalSchema(BaseModel):
    id: str
    outage_id: Optional[str] = None
    source_id: str
    signal_type: SignalTypeEnum
    timestamp: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    area_id: Optional[str] = None
    status: str
    confidence: float
    metadata_json: Optional[str] = None
    processed: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class CommunityReportSchema(BaseModel):
    id: str
    outage_id: Optional[str] = None
    session_id: str
    timestamp: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    area_id: Optional[str] = None
    power_status: str
    municipality: Optional[str] = None
    barangay: Optional[str] = None
    notes: Optional[str] = None
    device_info: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SourceSchema(BaseModel):
    id: str
    name: str
    source_type: SourceTypeEnum
    reliability: float
    status: SourceStatusEnum
    last_seen: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    latency_ms: Optional[int] = None
    metadata_json: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class OfficialAdvisorySchema(BaseModel):
    id: str
    outage_id: str
    source_id: str
    advisory_type: str
    title: Optional[str] = None
    content: Optional[str] = None
    url: Optional[str] = None
    published_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class PublicationEventSchema(BaseModel):
    id: str
    outage_id: str
    publisher_name: str
    status: str
    channel: str
    content: Optional[str] = None
    external_id: Optional[str] = None
    url: Optional[str] = None
    attempt_count: int
    last_error: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SystemEventSchema(BaseModel):
    id: str
    event_type: str
    message: str
    outage_id: Optional[str] = None
    source: Optional[str] = None
    metadata_json: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SensorNodeSchema(BaseModel):
    id: str
    name: str
    area_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_heartbeat: Optional[datetime] = None
    last_power_status: Optional[str] = None
    firmware_version: Optional[str] = None
    is_active: bool = True
    metadata_json: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReportPowerStatus(BaseModel):
    power_status: str = Field(..., pattern="^(off|on|out|restored)$")
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    municipality: Optional[str] = None
    barangay: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=500)
    session_id: Optional[str] = None


class StatusResponse(BaseModel):
    status: str
    active_outages: int
    last_updated: datetime
    outages: List[OutageSchema] = []


class MapAreaStatus(BaseModel):
    area_id: str
    area_name: str
    status: str
    confidence: float
    outage_id: Optional[str] = None
    started_at: Optional[datetime] = None
    restored_at: Optional[datetime] = None
    report_count: int = 0
