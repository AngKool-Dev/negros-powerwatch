import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from collections import defaultdict

from app.config import settings
from app.models import (
    Outage, OutageArea, OutageStatus, Signal, SignalType, CommunityReport,
    GeographicArea, Source, SourceType, SourceStatus, SystemEvent
)


class OutageEngine:
    def __init__(self, db_session):
        self.db = db_session
        self._ensure_sources()

    def _ensure_sources(self):
        default_sources = [
            ("community", SourceType.COMMUNITY, 0.7),
            ("noreco_ii", SourceType.NORECO_II, 0.9),
            ("ngcp", SourceType.NGCP, 0.9),
        ]
        for name, source_type, reliability in default_sources:
            source = self.db.query(Source).filter(Source.name == name).first()
            if not source:
                source = Source(
                    name=name,
                    source_type=source_type,
                    reliability=reliability,
                    status=SourceStatus.UNKNOWN,
                )
                self.db.add(source)
        self.db.flush()

    def _get_source(self, name: str) -> Source:
        source = self.db.query(Source).filter(Source.name == name).first()
        if not source:
            source = Source(
                name=name,
                source_type=SourceType.COMMUNITY,
                reliability=0.5,
                status=SourceStatus.UNKNOWN,
            )
            self.db.add(source)
            self.db.flush()
        return source

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _is_within_radius(self, lat1: float, lon1: float, lat2: float, lon2: float, radius_km: float) -> bool:
        return self._haversine_distance(lat1, lon1, lat2, lon2) <= radius_km

    def _find_active_outage_for_area(self, area_id: str, now: datetime) -> Optional[Outage]:
        return (
            self.db.query(Outage)
            .join(OutageArea)
            .filter(
                OutageArea.area_id == area_id,
                Outage.status.in_([
                    OutageStatus.POSSIBLE,
                    OutageStatus.DETECTED,
                    OutageStatus.COMMUNITY_CONFIRMED,
                    OutageStatus.OFFICIALLY_CONFIRMED,
                    OutageStatus.RESTORING,
                ]),
            )
            .order_by(Outage.created_at.desc())
            .first()
        )

    def _find_active_outage_nearby(
        self, latitude: float, longitude: float, radius_km: float, now: datetime
    ) -> Optional[Outage]:
        active_outages = (
            self.db.query(Outage)
            .join(OutageArea)
            .join(GeographicArea)
            .filter(
                Outage.status.in_([
                    OutageStatus.POSSIBLE,
                    OutageStatus.DETECTED,
                    OutageStatus.COMMUNITY_CONFIRMED,
                    OutageStatus.OFFICIALLY_CONFIRMED,
                    OutageStatus.RESTORING,
                ]),
                GeographicArea.latitude.is_not(None),
                GeographicArea.longitude.is_not(None),
            )
            .distinct()
            .all()
        )
        for outage in active_outages:
            for oa in outage.areas:
                if oa.area.latitude is not None and oa.area.longitude is not None:
                    if self._is_within_radius(latitude, longitude, oa.area.latitude, oa.area.longitude, radius_km):
                        return outage
        return None

    def process_community_report(self, report: CommunityReport) -> Outage:
        now = datetime.now(timezone.utc)
        source = self._get_source("community")
        source.last_seen = now
        self.db.add(source)

        outage = None
        if report.area_id:
            outage = self._find_active_outage_for_area(report.area_id, now)
        if not outage and report.latitude is not None and report.longitude is not None:
            outage = self._find_active_outage_nearby(
                report.latitude, report.longitude, settings.report_radius_km, now
            )

        if report.power_status in ("off", "out"):
            if outage is None:
                outage = Outage(
                    status=OutageStatus.POSSIBLE,
                    confidence=0.0,
                    report_count=1,
                    first_signal_at=report.timestamp,
                    started_at=report.timestamp,
                )
                self.db.add(outage)
                self.db.flush()

                if report.area_id:
                    oa = OutageArea(outage_id=outage.id, area_id=report.area_id)
                    self.db.add(oa)

                signal = Signal(
                    outage_id=outage.id,
                    source_id=source.id,
                    signal_type=SignalType.COMMUNITY_REPORT,
                    timestamp=report.timestamp,
                    latitude=report.latitude,
                    longitude=report.longitude,
                    area_id=report.area_id,
                    status="out",
                    confidence=0.1,
                    metadata_json=f'{{"report_id": "{report.id}"}}',
                    processed=True,
                )
                self.db.add(signal)
                self.db.flush()
            else:
                outage.report_count += 1
                outage.started_at = min(outage.started_at or report.timestamp, report.timestamp)
                outage.first_signal_at = min(outage.first_signal_at or report.timestamp, report.timestamp)

                if report.area_id:
                    existing = self.db.query(OutageArea).filter(
                        OutageArea.outage_id == outage.id,
                        OutageArea.area_id == report.area_id,
                    ).first()
                    if not existing:
                        oa = OutageArea(outage_id=outage.id, area_id=report.area_id)
                        self.db.add(oa)

                signal = Signal(
                    outage_id=outage.id,
                    source_id=source.id,
                    signal_type=SignalType.COMMUNITY_REPORT,
                    timestamp=report.timestamp,
                    latitude=report.latitude,
                    longitude=report.longitude,
                    area_id=report.area_id,
                    status="out",
                    confidence=0.1,
                    metadata_json=f'{{"report_id": "{report.id}"}}',
                    processed=True,
                )
                self.db.add(signal)

            self._update_outage_confidence(outage)
            self._transition_status(outage, now)

        elif report.power_status in ("on", "restored"):
            if outage is not None and outage.status in (
                OutageStatus.POSSIBLE, OutageStatus.DETECTED, OutageStatus.COMMUNITY_CONFIRMED,
                OutageStatus.OFFICIALLY_CONFIRMED, OutageStatus.RESTORING,
            ):
                now_ts = now.timestamp()
                if outage.restored_at is None or (now_ts - outage.restored_at.timestamp()) < settings.restoration_window_seconds:
                    outage.restored_at = report.timestamp
                self._transition_status(outage, now)

        self.db.flush()
        return outage

    def process_signal(self, signal: Signal) -> Optional[Outage]:
        now = datetime.now(timezone.utc)
        source = self._get_source(signal.source_id)
        source.last_seen = now
        self.db.add(source)

        outage = None
        if signal.outage_id:
            outage = self.db.query(Outage).filter(Outage.id == signal.outage_id).first()

        if signal.area_id:
            outage = self._find_active_outage_for_area(signal.area_id, now)

        if outage is None and signal.latitude is not None and signal.longitude is not None:
            outage = self._find_active_outage_nearby(
                signal.latitude, signal.longitude, settings.report_radius_km, now
            )

        if outage is None and signal.status == "out":
            outage = Outage(
                status=OutageStatus.POSSIBLE,
                confidence=0.0,
                report_count=0,
                first_signal_at=signal.timestamp,
                started_at=signal.timestamp,
            )
            self.db.add(outage)
            self.db.flush()

        if outage is not None:
            signal.outage_id = outage.id
            signal.processed = True
            if outage.first_signal_at is None or signal.timestamp < outage.first_signal_at:
                outage.first_signal_at = signal.timestamp
            if outage.started_at is None or signal.timestamp < outage.started_at:
                outage.started_at = signal.timestamp

            if signal.area_id:
                existing = self.db.query(OutageArea).filter(
                    OutageArea.outage_id == outage.id,
                    OutageArea.area_id == signal.area_id,
                ).first()
                if not existing:
                    oa = OutageArea(outage_id=outage.id, area_id=signal.area_id)
                    self.db.add(oa)

            if signal.signal_type == SignalType.OFFICIAL_ADVISORY:
                outage.official_confirmed_at = datetime.now(timezone.utc)

            self._update_outage_confidence(outage)
            self._transition_status(outage, now)

        self.db.add(signal)
        self.db.flush()
        return outage

    def _update_outage_confidence(self, outage: Outage):
        now = datetime.now(timezone.utc)
        signals = self.db.query(Signal).filter(Signal.outage_id == outage.id).all()
        reports = self.db.query(CommunityReport).filter(CommunityReport.outage_id == outage.id).all()

        report_count = outage.report_count or 0
        if report_count >= 20:
            base_confidence = 0.95
        elif report_count >= 10:
            base_confidence = 0.85
        elif report_count >= 5:
            base_confidence = 0.70
        elif report_count >= 3:
            base_confidence = 0.55
        elif report_count >= 1:
            base_confidence = 0.30
        else:
            base_confidence = 0.0

        unique_areas = len({r.area_id for r in reports if r.area_id})
        if unique_areas >= 3:
            base_confidence = min(1.0, base_confidence + 0.10)
        elif unique_areas >= 2:
            base_confidence = min(1.0, base_confidence + 0.05)

        has_official = any(s.signal_type == SignalType.OFFICIAL_ADVISORY for s in signals)
        if has_official:
            base_confidence = min(1.0, base_confidence + 0.15)

        outage.confidence = round(min(1.0, max(0.0, base_confidence)), 2)

    def _transition_status(self, outage: Outage, now: datetime):
        signals = self.db.query(Signal).filter(Signal.outage_id == outage.id).all()
        reports = self.db.query(CommunityReport).filter(CommunityReport.outage_id == outage.id).all()
        has_official = any(s.signal_type == SignalType.OFFICIAL_ADVISORY for s in signals)

        if outage.status == OutageStatus.POSSIBLE:
            if outage.report_count >= settings.report_min_reports or has_official:
                outage.status = OutageStatus.DETECTED if not has_official else OutageStatus.OFFICIALLY_CONFIRMED
                outage.detected_at = now
                self._log_event("OUTAGE_DETECTED", outage)
            else:
                return

        if outage.status == OutageStatus.DETECTED:
            if outage.report_count >= 5 or has_official:
                outage.status = OutageStatus.COMMUNITY_CONFIRMED if not has_official else OutageStatus.OFFICIALLY_CONFIRMED
                if has_official:
                    outage.official_confirmed_at = now
                self._log_event("OUTAGE_COMMUNITY_CONFIRMED", outage)

        if outage.status in (OutageStatus.COMMUNITY_CONFIRMED, OutageStatus.OFFICIALLY_CONFIRMED, OutageStatus.DETECTED):
            if outage.restored_at is not None:
                outage.status = OutageStatus.RESTORING
                self._log_event("OUTAGE_RESTORING", outage)

        if outage.status == OutageStatus.RESTORING:
            if outage.restored_at is not None and (now - outage.restored_at).total_seconds() >= 60:
                outage.status = OutageStatus.RESTORED
                outage.closed_at = now
                self._log_event("OUTAGE_RESTORED", outage)

    def _log_event(self, event_type: str, outage: Outage):
        event = SystemEvent(
            event_type=event_type,
            message=f"Outage {outage.id} transitioned to {outage.status}",
            outage_id=outage.id,
            source="engine",
        )
        self.db.add(event)
        self.db.flush()

    def close_stale_outages(self) -> List[Outage]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.stale_signal_seconds)
        stale = (
            self.db.query(Outage)
            .filter(
                Outage.status.in_([
                    OutageStatus.POSSIBLE, OutageStatus.DETECTED,
                    OutageStatus.COMMUNITY_CONFIRMED, OutageStatus.OFFICIALLY_CONFIRMED,
                ]),
                Outage.updated_at < cutoff,
            )
            .all()
        )
        for outage in stale:
            if outage.report_count < 2:
                outage.status = OutageStatus.CLOSED
                outage.closed_at = datetime.now(timezone.utc)
                self._log_event("OUTAGE_CLOSED_STALE", outage)
        self.db.flush()
        return stale

    def get_active_outages(self) -> List[Outage]:
        return (
            self.db.query(Outage)
            .filter(
                Outage.status.in_([
                    OutageStatus.POSSIBLE,
                    OutageStatus.DETECTED,
                    OutageStatus.COMMUNITY_CONFIRMED,
                    OutageStatus.OFFICIALLY_CONFIRMED,
                    OutageStatus.RESTORING,
                ])
            )
            .order_by(Outage.created_at.desc())
            .all()
        )

    def get_outage_by_id(self, outage_id: str) -> Optional[Outage]:
        return self.db.query(Outage).filter(Outage.id == outage_id).first()
