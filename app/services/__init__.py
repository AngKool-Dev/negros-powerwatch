from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
import asyncio

from app.models import (
    Outage, OutageStatus, CommunityReport, Signal, OutageArea,
    GeographicArea, SystemEvent, Source, SourceStatus, SourceType
)
from app.engine import OutageEngine
from app.providers.community import CommunityProvider
from app.providers.facebook import FacebookProvider
from app.config import settings

_clients: List[asyncio.Queue] = []


async def broadcast_event(data: dict):
    for queue in list(_clients):
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            pass


def _schedule_broadcast(data: dict):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_event(data))
    except RuntimeError:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(broadcast_event(data))
        except RuntimeError:
            pass


class ReportService:
    def __init__(self, db: Session):
        self.db = db
        self.engine = OutageEngine(db)
        self.community_provider = CommunityProvider()
        self.facebook_provider = FacebookProvider()

    def submit_report(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        source = self.db.query(Source).filter(Source.name == "community").first()
        if not source:
            source = Source(name="community", source_type=SourceType.COMMUNITY, reliability=0.7, status=SourceStatus.UNKNOWN)
            self.db.add(source)
            self.db.flush()

        session_id = report_data.get("session_id") or "anonymous"
        recent = self.db.query(CommunityReport).filter(
            CommunityReport.session_id == session_id,
            CommunityReport.power_status == report_data.get("power_status"),
            CommunityReport.created_at >= datetime.now(timezone.utc) - timedelta(seconds=settings.report_duplicate_window_seconds),
        ).first()
        if recent:
            return {"status": "duplicate", "existing_report_id": recent.id}

        area = None
        if report_data.get("area_id"):
            area = self.db.query(GeographicArea).filter(GeographicArea.id == report_data["area_id"]).first()
        elif report_data.get("municipality"):
            area = self.db.query(GeographicArea).filter(
                GeographicArea.name.ilike(f"%{report_data['municipality']}%"),
                GeographicArea.area_type == "municipality",
            ).first()

        report = CommunityReport(
            session_id=session_id,
            timestamp=datetime.now(timezone.utc),
            latitude=report_data.get("latitude"),
            longitude=report_data.get("longitude"),
            area_id=area.id if area else None,
            power_status=report_data.get("power_status", "unknown"),
            municipality=report_data.get("municipality"),
            barangay=report_data.get("barangay"),
            notes=report_data.get("notes"),
            device_info=report_data.get("device_info"),
            ip_address=report_data.get("ip_address"),
        )
        self.db.add(report)
        self.db.flush()

        outage = self.engine.process_community_report(report)

        self.db.add(SystemEvent(
            event_type="REPORT_RECEIVED",
            message=f"Community report received: {report.power_status}",
            outage_id=outage.id if outage else None,
            source="community",
            metadata_json=f'{{"report_id": "{report.id}"}}',
        ))
        self.db.flush()

        _schedule_broadcast({
            "type": "report_received",
            "report_id": report.id,
            "outage_id": outage.id if outage else None,
            "outage_status": outage.status.value if outage else None,
        })

        return {
            "status": "accepted",
            "report_id": report.id,
            "outage_id": outage.id if outage else None,
            "outage_status": outage.status.value if outage else None,
        }

    def get_status(self) -> Dict[str, Any]:
        active_outages = self.engine.get_active_outages()
        return {
            "status": "operational",
            "active_outages": len(active_outages),
            "outages": active_outages,
            "last_updated": datetime.now(timezone.utc),
        }

    def get_active_outages(self) -> List[Outage]:
        return self.engine.get_active_outages()

    def get_outage_by_id(self, outage_id: str) -> Optional[Outage]:
        return self.engine.get_outage_by_id(outage_id)

    def close_stale(self) -> List[Outage]:
        return self.engine.close_stale_outages()

    async def scan_sources(self) -> Dict[str, Any]:
        providers = [
            self.facebook_provider,
        ]
        total_signals = 0
        results = {}
        for provider in providers:
            try:
                signals = await provider.fetch_signals()
                results[provider.name] = {
                    "signals_found": len(signals),
                    "status": "ok"
                }
                for sig in signals:
                    area = None
                    if sig.get("area"):
                        area = self.db.query(GeographicArea).filter(
                            GeographicArea.name.ilike(f"%{sig['area']}%")
                        ).first()

                    source = self.db.query(Source).filter(Source.name == provider.name).first()
                    if not source:
                        source = Source(
                            name=provider.name,
                            source_type=SourceType.COMMUNITY,
                            reliability=0.5,
                            status=SourceStatus.UNKNOWN,
                        )
                        self.db.add(source)
                        self.db.flush()

                    source.last_seen = datetime.now(timezone.utc)
                    source.status = SourceStatus.HEALTHY
                    self.db.add(source)
                    self.db.flush()

                    existing_signal = self.db.query(Signal).filter(
                        Signal.source_id == source.id,
                        Signal.metadata_json.like(f'%"source_id": "{sig.get("source_id", "")}"')
                    ).first()
                    if existing_signal:
                        continue

                    metadata = {
                        "raw_text": sig.get("raw_text"),
                        "score": sig.get("score"),
                        "barangay": sig.get("barangay"),
                        "source_url": sig.get("source_url"),
                        "source_id": sig.get("source_id"),
                        "page_id": sig.get("metadata", {}).get("page_id"),
                        "author": sig.get("metadata", {}).get("author"),
                        "source_name": sig.get("metadata", {}).get("source_name"),
                    }

                    signal = Signal(
                        source_id=source.id,
                        signal_type=sig.get("signal_type", SignalType.SCRAPER),
                        timestamp=sig.get("timestamp", datetime.now(timezone.utc)),
                        latitude=None,
                        longitude=None,
                        area_id=area.id if area else None,
                        status=sig.get("status", "out"),
                        confidence=sig.get("confidence", 0.5),
                        metadata_json=str(metadata),
                    )
                    self.db.add(signal)
                    self.db.flush()
                    total_signals += 1
            except Exception as e:
                results[provider.name] = {
                    "signals_found": 0,
                    "status": f"error: {str(e)}"
                }
        self.db.commit()
        await broadcast_event({
            "type": "scan_complete",
            "total_signals": total_signals,
            "providers": results,
        })
        return {
            "total_signals": total_signals,
            "providers": results
        }
