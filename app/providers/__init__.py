from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.models import Signal, Source, SourceType, SignalType, GeographicArea
from app.schemas import SignalSchema


class SignalProvider(ABC):
    def __init__(self, name: str, source_type: SourceType):
        self.name = name
        self.source_type = source_type
        self._source: Optional[Source] = None

    @abstractmethod
    async def fetch_signals(self, since: Optional[datetime] = None) -> List[SignalSchema]:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass

    def get_or_create_source(self, db_session) -> Source:
        source = db_session.query(Source).filter(Source.name == self.name).first()
        if not source:
            source = Source(
                name=self.name,
                source_type=self.source_type,
                reliability=0.5,
                status=SourceStatus.UNKNOWN,
            )
            db_session.add(source)
            db_session.flush()
        return source
