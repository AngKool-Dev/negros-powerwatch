from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional


class PostCollectionError(Exception):
    pass


class AuthenticationError(PostCollectionError):
    pass


class RateLimitError(PostCollectionError):
    pass


class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, source_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass
