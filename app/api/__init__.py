from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
import asyncio
import json

from fastapi.responses import EventSourceResponse

from app.db import get_db
from app.models import Outage, OutageStatus, CommunityReport, GeographicArea
from app.schemas import (
    OutageSchema, ReportPowerStatus, StatusResponse, MapAreaStatus
)
from app.services import ReportService, broadcast_event, _clients
from app.config import settings

router = APIRouter()


async def event_generator(request: Request):
    queue = asyncio.Queue()
    _clients.append(queue)
    try:
        while True:
            if await request.is_disconnected():
                break
            data = await queue.get()
            yield f"data: {json.dumps(data)}\n\n"
    finally:
        _clients.remove(queue)


@router.get("/status", response_model=StatusResponse)
def get_status(db: Session = Depends(get_db)):
    service = ReportService(db)
    data = service.get_status()
    return StatusResponse(
        status=data["status"],
        active_outages=data["active_outages"],
        last_updated=data["last_updated"],
        outages=data.get("outages", []),
    )


@router.get("/outages", response_model=List[OutageSchema])
def get_outages(db: Session = Depends(get_db)):
    service = ReportService(db)
    return service.get_active_outages()


@router.get("/outages/active", response_model=List[OutageSchema])
def get_active_outages(db: Session = Depends(get_db)):
    service = ReportService(db)
    return service.get_active_outages()


@router.get("/outages/{outage_id}", response_model=OutageSchema)
def get_outage(outage_id: str, db: Session = Depends(get_db)):
    service = ReportService(db)
    outage = service.get_outage_by_id(outage_id)
    if not outage:
        raise HTTPException(status_code=404, detail="Outage not found")
    return outage


@router.post("/reports")
def submit_report(report: ReportPowerStatus, request: Request, db: Session = Depends(get_db)):
    client_host = request.client.host if request.client else None
    report_data = report.model_dump()
    report_data["ip_address"] = client_host
    report_data["session_id"] = report_data.get("session_id") or f"anon-{client_host}"

    service = ReportService(db)
    result = service.submit_report(report_data)

    if result["status"] == "duplicate":
        raise HTTPException(status_code=429, detail="Duplicate report")

    return result


@router.post("/reports/power-off")
def report_power_off(report: ReportPowerStatus, request: Request, db: Session = Depends(get_db)):
    report.power_status = "off"
    return submit_report(report, request, db)


@router.post("/reports/power-restored")
def report_power_restored(report: ReportPowerStatus, request: Request, db: Session = Depends(get_db)):
    report.power_status = "restored"
    return submit_report(report, request, db)


@router.post("/scan")
async def scan_sources(db: Session = Depends(get_db)):
    service = ReportService(db)
    result = await service.scan_sources()
    return result


@router.get("/admin/facebook/status")
async def get_facebook_status(db: Session = Depends(get_db)):
    service = ReportService(db)
    provider = service.facebook_provider

    sources = settings.get_facebook_sources()
    source_statuses = []
    for src in sources:
        source_statuses.append({
            "name": src.get("name"),
            "page_id": src.get("page_id"),
            "enabled": src.get("enabled", True),
        })

    return {
        "enabled": settings.facebook_enabled,
        "access_token_configured": bool(settings.facebook_access_token),
        "poll_interval_minutes": settings.facebook_poll_interval_minutes,
        "sources": source_statuses,
        "last_success": provider.last_success.isoformat() if provider.last_success else None,
        "last_error": provider.last_error,
        "health": await provider.health_check(),
    }


@router.get("/map/reports")
def get_map_reports(db: Session = Depends(get_db)):
    reports = db.query(CommunityReport).filter(
        CommunityReport.latitude.is_not(None),
        CommunityReport.longitude.is_not(None),
        CommunityReport.power_status == "out"
    ).all()

    return [
        {
            "id": r.id,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "timestamp": r.timestamp,
            "area_id": r.area_id,
            "municipality": r.municipality,
            "barangay": r.barangay,
        }
        for r in reports
    ]


@router.get("/map/status", response_model=List[MapAreaStatus])
def get_map_status(db: Session = Depends(get_db)):
    service = ReportService(db)
    outages = service.get_active_outages()
    area_map: Dict[str, Dict[str, Any]] = {}
    for outage in outages:
        for oa in outage.areas:
            area = db.query(GeographicArea).filter(GeographicArea.id == oa.area_id).first()
            if not area:
                continue
            key = area.id
            if key not in area_map:
                area_map[key] = {
                    "area_id": area.id,
                    "area_name": area.name,
                    "status": outage.status.value,
                    "confidence": outage.confidence,
                    "outage_id": outage.id,
                    "started_at": outage.started_at,
                    "restored_at": outage.restored_at,
                    "report_count": outage.report_count,
                    "center": [area.latitude, area.longitude] if area.latitude and area.longitude else None,
                }
    return list(area_map.values())


@router.get("/events")
async def get_events(request: Request):
    return EventSourceResponse(event_generator(request))
