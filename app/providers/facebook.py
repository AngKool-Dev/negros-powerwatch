from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
import re
import logging

from app.models import SignalType, Source, SourceType, SourceStatus, GeographicArea, Signal
from app.providers import SignalProvider
from app.collectors.facebook import FacebookGraphCollector, AuthenticationError, RateLimitError, PostCollectionError
from app.config import settings

logger = logging.getLogger(__name__)

NEGROS_ORIENTAL_MUNICIPALITIES = {
    "amlan", "ayungon", "bacong", "basay", "bindoy", "payabon", "dauin", "jimalalud",
    "la libertad", "mabinay", "manjuyod", "pamplona", "san jose",
    "santa catalina", "siaton", "sibulan", "tayasan", "valencia", "luzuriaga",
    "vallehermoso", "zamboanguita", "dumaguete", "dumaguete city",
    "bais", "bais city", "canlaon", "canlaon city",
    "guihulngan", "guihulngan city", "tanjay", "tanjay city",
    "bayawan", "bayawan city", "negros oriental", "negros"
}

LOCATION_ALIASES = {
    "ayquitan": "amlan",
    "ayuquitan": "amlan",
    "payabon": "bindoy",
    "luzuriaga": "valencia",
}

OUTAGE_KEYWORDS = {
    "+5": [
        "brownout", "brown out", "power outage", "power interruption", "power failure",
        "power loss", "no electricity", "no electric", "no power", "electricity gone",
        "kuryente", "walay kuryente", "wala'y kuryente", "walay suga", "walay power",
        "naputol ang kuryente", "naputol kuryente", "naputol among kuryente",
        "wala mi kuryente", "wala kami kuryente", "walang kuryente",
        "sudden brownout", "sudden power outage", "unexpected brownout", "unexpected outage",
        "tripped", "transformer explosion", "transformer problem", "transformer busted",
        "naputol nga linya", "naputol ang linya", "nahugno poste",
        "sunog", "electrical fire", "spark",
    ],
    "+3": [
        "kuryente", "linya", "poste", "pundok",
        "brownout diri", "brownout sa amo", "brownout sa amoa",
        "wala gihapon kuryente", "wala gihapon power",
        "dugay na brownout", "pila na ka oras walay kuryente",
        "3 hours na walay kuryente", "2 hours na walay kuryente",
        "1 hour na walay kuryente",
    ],
    "+1": [
        "scheduled brownout", "scheduled outage", "planned outage",
        "power interruption advisory", "brownout schedule", "brownout advisory",
        "outage advisory", "power advisory", "maintenance", "maintenance shutdown",
        "line maintenance", "repair", "repair work", "emergency maintenance",
        "advisory", "schedule",
    ],
    "-5": [
        "kuryente nibalik", "nibalik ang kuryente", "nibalik na ang kuryente",
        "may kuryente na", "naa nay kuryente", "naa na kuryente", "naay kuryente",
        "power restored", "electricity restored", "power back", "kuryente balik",
        "siga na", "nibalik na", "naa na",
    ],
}

RESTORATION_KEYWORDS = {
    "kuryente nibalik", "nibalik ang kuryente", "nibalik na ang kuryente",
    "may kuryente na", "naa nay kuryente", "naa na kuryente", "naay kuryente",
    "power restored", "electricity restored", "power back", "kuryente balik",
    "siga na", "nibalik na", "naa na",
}

PLANNED_KEYWORDS = {
    "scheduled brownout", "scheduled outage", "planned outage",
    "power interruption advisory", "brownout schedule", "brownout advisory",
    "outage advisory", "power advisory", "maintenance", "maintenance shutdown",
    "line maintenance", "repair", "repair work", "emergency maintenance",
}


class FacebookProvider(SignalProvider):
    def __init__(self):
        super().__init__("facebook", SourceType.COMMUNITY)
        self.collector = FacebookGraphCollector(access_token=settings.facebook_access_token)

    async def fetch_signals(self, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        if not settings.facebook_enabled:
            logger.info("Facebook monitoring disabled")
            return []

        sources = settings.get_facebook_sources()
        if not sources:
            logger.info("No Facebook sources configured")
            return []

        all_signals = []
        for source_config in sources:
            if not source_config.get("enabled", True):
                continue
            try:
                posts = await self.collector.collect(source_config)
                for post in posts:
                    signal = self._post_to_signal(post, source_config)
                    if signal:
                        all_signals.append(signal)
            except AuthenticationError:
                logger.error("Facebook authentication failed. Check FACEBOOK_ACCESS_TOKEN.")
                break
            except RateLimitError as e:
                logger.warning("Facebook rate limited: %s", e)
                break
            except PostCollectionError as e:
                logger.error("Facebook collection error for %s: %s", source_config.get("name"), e)
                continue
            except Exception as e:
                logger.exception("Unexpected error collecting from %s", source_config.get("name"))
                continue

        return all_signals

    def _post_to_signal(self, post: Dict[str, Any], source_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        message = post.get("message", "")
        if not message:
            return None

        lower_message = message.lower()
        score, is_restoration, is_planned = self._score_post(lower_message)

        if score < 5 and not is_restoration:
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