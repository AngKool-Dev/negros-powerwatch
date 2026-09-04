import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.db import Base, get_db
from app.engine import OutageEngine
from app.models import (
    Outage, OutageStatus, Signal, SignalType, CommunityReport,
    GeographicArea, Source, SourceType
)


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


class TestOutageEngine:
    def test_engine_initialization(self, db):
        engine = OutageEngine(db)
        sources = db.query(Source).all()
        assert len(sources) == 3

    def test_community_report_creates_outage(self, db):
        engine = OutageEngine(db)
        area = GeographicArea(name="Siaton", area_type="municipality", latitude=9.8, longitude=123.5)
        db.add(area)
        db.flush()

        report = CommunityReport(
            session_id="test-1",
            timestamp=datetime.now(timezone.utc),
            latitude=9.8,
            longitude=123.5,
            area_id=area.id,
            power_status="off",
        )
        db.add(report)
        db.flush()

        outage = engine.process_community_report(report)
        assert outage is not None
        assert outage.status == OutageStatus.POSSIBLE

    def test_multiple_reports_detect_outage(self, db):
        engine = OutageEngine(db)
        area = GeographicArea(name="Siaton", area_type="municipality", latitude=9.8, longitude=123.5)
        db.add(area)
        db.flush()

        outage = None
        for i in range(3):
            report = CommunityReport(
                session_id=f"test-{i}",
                timestamp=datetime.now(timezone.utc) + timedelta(seconds=i * 10),
                latitude=9.8 + i * 0.001,
                longitude=123.5 + i * 0.001,
                area_id=area.id,
                power_status="off",
            )
            db.add(report)
            db.flush()
            outage = engine.process_community_report(report)

        assert outage is not None
        assert outage.report_count == 3
        assert outage.status == OutageStatus.DETECTED

    def test_restoration_detection(self, db):
        engine = OutageEngine(db)
        area = GeographicArea(name="Siaton", area_type="municipality", latitude=9.8, longitude=123.5)
        db.add(area)
        db.flush()

        report = CommunityReport(
            session_id="test-1",
            timestamp=datetime.now(timezone.utc),
            latitude=9.8,
            longitude=123.5,
            area_id=area.id,
            power_status="off",
        )
        db.add(report)
        db.flush()
        outage = engine.process_community_report(report)

        assert outage.status == OutageStatus.POSSIBLE

        for i in range(2, 5):
            report = CommunityReport(
                session_id=f"test-{i}",
                timestamp=datetime.now(timezone.utc) + timedelta(seconds=i * 10),
                latitude=9.8 + i * 0.001,
                longitude=123.5 + i * 0.001,
                area_id=area.id,
                power_status="off",
            )
            db.add(report)
            db.flush()
            outage = engine.process_community_report(report)

        assert outage.status == OutageStatus.DETECTED

        restored_report = CommunityReport(
            session_id="test-restore",
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=60),
            latitude=9.8,
            longitude=123.5,
            area_id=area.id,
            power_status="restored",
        )
        db.add(restored_report)
        db.flush()
        outage = engine.process_community_report(restored_report)
        assert outage.status in (OutageStatus.RESTORING, OutageStatus.RESTORED)

    def test_get_active_outages(self, db):
        engine = OutageEngine(db)
        active = engine.get_active_outages()
        assert active == []
