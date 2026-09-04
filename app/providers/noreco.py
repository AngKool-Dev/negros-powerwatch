from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
import re
import logging

from app.models import SignalType, Source, SourceType, SourceStatus, GeographicArea
from app.providers import SignalProvider
from app.providers.facebook import (
    NEGROS_ORIENTAL_MUNICIPALITIES,
    LOCATION_ALIASES,
    OUTAGE_KEYWORDS,
    RESTORATION_KEYWORDS,
    PLANNED_KEYWORDS,
)
from app.collectors.facebook import FacebookGraphCollector, AuthenticationError, RateLimitError, PostCollectionError
from app.config import settings

logger = logging.getLogger(__name__)


class NORECOProvider(SignalProvider):
    def __init__(self):
        super().__init__("noreco_ii", SourceType.NORECO_II)
        self.collector = FacebookGraphCollector(access_token=settings.facebook_access_token)

    async def fetch_signals(self, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        source_config = {
            "name": "NORECO II",
            "page_id": "NORECO2Official",
            "enabled": settings.facebook_enabled,
            "limit": 20,
        }
        return await self._collect_and_process(source_config)

    async def _collect_and_process(self, source_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not source_config.get("enabled", True):
            return []

        try:
            posts = await self.collector.collect(source_config)
        except AuthenticationError:
            logger.error("Facebook authentication failed for %s. Check FACEBOOK_ACCESS_TOKEN.", source_config.get("name"))
            return []
        except RateLimitError as e:
            logger.warning("Facebook rate limited for %s: %s", source_config.get("name"), e)
            return []
        except PostCollectionError as e:
            logger.error("Collection error for %s: %s", source_config.get("name"), e)
            return []
        except Exception:
            logger.exception("Unexpected error collecting from %s", source_config.get("name"))
            return []

        signals = []
        for post in posts:
            signal = self._post_to_signal(post, source_config)
            if signal:
                signals.append(signal)
        return signals

    def _post_to_signal(self, post: Dict[str, Any], source_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        message = post.get("message", "")
        if not message:
            return None

        lower_message = message.lower()
        score, is_restoration, is_planned = self._score_post(lower_message)

        if score < 5:
            return None

        area, barangay = self._detect_location(lower_message)

        created_at = post.get("created_at", datetime.now(timezone.utc).isoformat())
        try:
            timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            timestamp = datetime.now(timezone.utc)

        confidence = min(0.95, max(0.2, score / 15.0))
        status = "restored" if is_restoration else ("planned" if is_planned else "out")

        return {
            "signal_type": SignalType.SCRAPER,
            "status": status,
            "confidence": confidence,
            "area": area,
            "barangay": barangay,
            "score": score,
            "raw_text": message[:1000],
            "source_url": post.get("url", ""),
            "source_id": post.get("source_id", ""),
            "timestamp": timestamp,
            "metadata": {
                "page_id": post.get("page_id"),
                "author": post.get("author"),
                "collected_at": post.get("collected_at"),
                "source_name": source_config.get("name"),
            },
        }

    def _score_post(self, text: str) -> Tuple[int, bool, bool]:
        score = 0
        is_restoration = False
        is_planned = False

        for keyword in RESTORATION_KEYWORDS:
            if keyword in text:
                is_restoration = True
                score -= 5
                break

        for keyword in PLANNED_KEYWORDS:
            if keyword in text:
                is_planned = True
                score += 1

        for score_val, keywords in OUTAGE_KEYWORDS.items():
            val = int(score_val)
            for keyword in keywords:
                if keyword in text:
                    score += val

        return score, is_restoration, is_planned

    def _detect_location(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        found_muni = None
        found_barangay = None

        for alias, canonical in LOCATION_ALIASES.items():
            if alias in text:
                text = text.replace(alias, canonical)

        for muni in NEGROS_ORIENTAL_MUNICIPALITIES:
            if muni in text:
                found_muni = muni.title()
                break

        barangay_match = re.search(r'(?:barangay|brgy\.?|brgy|purok|sitio)\s+([a-z0-9 ]+)', text)
        if barangay_match:
            found_barangay = barangay_match.group(1).strip().title()

        return found_muni, found_barangay

    async def health_check(self) -> bool:
        return self.collector.health_check()

    @property
    def last_success(self) -> Optional[datetime]:
        return self.collector.last_success

    @property
    def last_error(self) -> Optional[str]:
        return self.collector.last_error
