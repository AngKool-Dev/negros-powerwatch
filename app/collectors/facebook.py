import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import asyncio

import httpx

from app.collectors.base import BaseCollector, PostCollectionError, AuthenticationError, RateLimitError

logger = logging.getLogger(__name__)


class FacebookGraphCollector(BaseCollector):
    GRAPH_API_VERSION = "v18.0"
    BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
    DEFAULT_FIELDS = "id,message,created_time,permalink_url,from"

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token
        self._last_success: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._rate_limit_until: float = 0.0

    async def collect(self, source_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.access_token:
            raise AuthenticationError("FACEBOOK_ACCESS_TOKEN not configured")

        page_id = source_config.get("page_id") or source_config.get("url", "").rstrip("/").split("/")[-1]
        if not page_id:
            raise PostCollectionError("No page_id or URL configured for Facebook source")

        limit = source_config.get("limit", 20)
        max_retries = source_config.get("max_retries", 3)
        retry_delay = source_config.get("retry_delay", 5)

        for attempt in range(1, max_retries + 1):
            try:
                return await self._fetch_posts(page_id, limit)
            except RateLimitError:
                if attempt == max_retries:
                    raise
                wait = retry_delay * attempt
                logger.warning("Facebook rate limited, backing off %ds (attempt %d/%d)", wait, attempt, max_retries)
                await asyncio.sleep(wait)
            except AuthenticationError:
                raise
            except PostCollectionError:
                raise

        return []

    async def _fetch_posts(self, page_id: str, limit: int) -> List[Dict[str, Any]]:
        now = time.time()
        if now < self._rate_limit_until:
            raise RateLimitError(f"Rate limited until {self._rate_limit_until}")

        url = f"{self.BASE_URL}/{page_id}/posts"
        params = {
            "access_token": self.access_token,
            "fields": self.DEFAULT_FIELDS,
            "limit": limit,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            self._rate_limit_until = time.time() + retry_after
            raise RateLimitError(f"Rate limited, retry after {retry_after}s")

        if response.status_code == 401 or response.status_code == 403:
            raise AuthenticationError(f"Facebook auth failed: {response.status_code}")

        if response.status_code != 200:
            raise PostCollectionError(f"Facebook API error: {response.status_code} {response.text[:200]}")

        data = response.json()
        posts = data.get("data", [])

        normalized = []
        for post in posts:
            normalized.append(self._normalize_post(post, page_id))

        self._last_success = datetime.now(timezone.utc)
        self._last_error = None
        logger.info("Collected %d posts from Facebook page %s", len(normalized), page_id)
        return normalized

    def _normalize_post(self, post: Dict[str, Any], page_id: str) -> Dict[str, Any]:
        message = post.get("message", "") or ""
        created_time = post.get("created_time")
        if created_time:
            try:
                created_dt = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                created_dt = datetime.now(timezone.utc)
        else:
            created_dt = datetime.now(timezone.utc)

        return {
            "source": "facebook",
            "source_id": post.get("id", ""),
            "page_id": page_id,
            "author": (post.get("from", {}) or {}).get("name", page_id),
            "message": message.strip(),
            "created_at": created_dt.isoformat(),
            "url": post.get("permalink_url", ""),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "raw_post": post,
            },
        }

    async def health_check(self) -> bool:
        if not self.access_token:
            return False
        try:
            url = f"{self.BASE_URL}/me"
            params = {"access_token": self.access_token}
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)
            return response.status_code == 200
        except Exception:
            return False

    @property
    def last_success(self) -> Optional[datetime]:
        return self._last_success

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
