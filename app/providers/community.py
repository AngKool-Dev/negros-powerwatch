from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import uuid

from app.models import SignalType, Signal, Source, SourceType, SourceStatus, GeographicArea
from app.schemas import SignalSchema
from app.providers import SignalProvider


class CommunityProvider(SignalProvider):
    def __init__(self):
        super().__init__("community", SourceType.COMMUNITY)

    async def fetch_signals(self, since: Optional[datetime] = None) -> List[SignalSchema]:
        return []

    async def health_check(self) -> bool:
        return True

    def create_report_signal(self, db_session, report_data: Dict[str, Any]) -> Signal:
        source = self.get_or_create_source(db_session)
        source.last_seen = datetime.now(timezone.utc)
        source.status = SourceStatus.HEALTHY
        db_session.add(source)
        db_session.flush()

        signal = Signal(
            source_id=source.id,
            signal_type=SignalType.COMMUNITY_REPORT,
            timestamp=datetime.now(timezone.utc),
            latitude=report_data.get("latitude"),
            longitude=report_data.get("longitude"),
            area_id=report_data.get("area_id"),
            status=report_data.get("power_status", "unknown"),
            confidence=0.1,
            metadata_json=report_data.get("notes"),
        )
        db_session.add(signal)
        db_session.flush()
        return signal
