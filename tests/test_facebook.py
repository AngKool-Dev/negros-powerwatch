import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.collectors.facebook import FacebookGraphCollector, AuthenticationError, RateLimitError, PostCollectionError
from app.providers.noreco import NORECOProvider
from app.providers.ngcp import NGCPProvider
from app.providers.facebook import FacebookProvider
from app.config import Settings

PHT = ZoneInfo("Asia/Manila")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
REQUIRED_LGUS = [
    "Amlan", "Ayungon", "Bacong", "Basay", "Bindoy", "Dauin", "Jimalalud",
    "La Libertad", "Mabinay", "Manjuyod", "Pamplona", "San Jose",
    "Santa Catalina", "Siaton", "Sibulan", "Tayasan", "Valencia",
    "Vallehermoso", "Zamboanguita", "Dumaguete", "Bais", "Canlaon",
    "Guihulngan", "Tanjay", "Bayawan"
]


class TestFacebookCollector:
    def test_auth_error_without_token(self):
        collector = FacebookGraphCollector(access_token=None)
        with pytest.raises(AuthenticationError):
            import asyncio
            asyncio.run(collector.collect({"page_id": "test"}))

    @patch("httpx.AsyncClient.get")
    def test_successful_collection(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "post123",
                    "message": "Brownout in Siaton today",
                    "created_time": "2026-09-04T11:32:36Z",
                    "permalink_url": "https://facebook.com/post123",
                    "from": {"name": "NORECO II"},
                }
            ]
        }
        mock_get.return_value = mock_response

        collector = FacebookGraphCollector(access_token="test-token")
        import asyncio
        posts = asyncio.run(collector.collect({"page_id": "NORECO2Official"}))
        assert len(posts) == 1
        assert posts[0]["message"] == "Brownout in Siaton today"
        assert posts[0]["source_id"] == "post123"

    @patch("httpx.AsyncClient.get")
    def test_rate_limit_retry(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "1"}
        mock_get.return_value = mock_response

        collector = FacebookGraphCollector(access_token="test-token")
        with pytest.raises(RateLimitError):
            import asyncio
            asyncio.run(collector.collect({"page_id": "test"}))

    @patch("httpx.AsyncClient.get")
    def test_auth_failure(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        collector = FacebookGraphCollector(access_token="bad-token")
        with pytest.raises(AuthenticationError):
            import asyncio
            asyncio.run(collector.collect({"page_id": "test"}))

    @patch("httpx.AsyncClient.get")
    def test_malformed_response(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"unexpected": "format"}
        mock_get.return_value = mock_response

        collector = FacebookGraphCollector(access_token="test-token")
        import asyncio
        posts = asyncio.run(collector.collect({"page_id": "test"}))
        assert posts == []

    @patch("httpx.AsyncClient.get")
    def test_health_check_with_token(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        collector = FacebookGraphCollector(access_token="test-token")
        import asyncio
        assert asyncio.run(collector.health_check()) is True

    def test_health_check_without_token(self):
        collector = FacebookGraphCollector(access_token=None)
        import asyncio
        assert asyncio.run(collector.health_check()) is False


class TestFacebookScoring:
    @pytest.fixture
    def provider(self):
        with patch("app.providers.facebook.settings") as mock_settings:
            mock_settings.facebook_access_token = "test-token"
            mock_settings.facebook_enabled = True
            mock_settings.get_facebook_sources.return_value = []
            return FacebookProvider()

    def test_brownout_detection(self, provider):
        score, restoration, planned = provider._score_post("brownout diri sa Siaton")
        assert score >= 5
        assert restoration is False
        assert planned is False

    def test_restoration_detection(self, provider):
        score, restoration, planned = provider._score_post("nibalik na ang kuryente")
        assert restoration is True
        assert score < 0

    def test_bisaya_detection(self, provider):
        score, restoration, planned = provider._score_post("walay kuryente diri sa amo")
        assert score >= 5
        assert restoration is False

    def test_planned_outage_detection(self, provider):
        score, restoration, planned = provider._score_post("scheduled brownout tomorrow")
        assert planned is True
        assert score >= 5

    def test_multiple_keywords(self, provider):
        score, restoration, planned = provider._score_post("power outage and transformer problem in Valencia")
        assert score >= 10

    def test_irrelevant_post(self, provider):
        score, restoration, planned = provider._score_post("nice weather today")
        assert score < 5


class TestLocationExtraction:
    @pytest.fixture
    def provider(self):
        with patch("app.providers.facebook.settings") as mock_settings:
            mock_settings.facebook_access_token = "test-token"
            mock_settings.facebook_enabled = True
            mock_settings.get_facebook_sources.return_value = []
            return FacebookProvider()

    def test_municipality_detection(self, provider):
        area, brgy = provider._detect_location("brownout in siaton")
        assert area == "Siaton"

    def test_city_detection(self, provider):
        area, brgy = provider._detect_location("power outage in dumaguete city")
        assert area == "Dumaguete City"

    def test_barangay_detection(self, provider):
        area, brgy = provider._detect_location("brownout diri sa barangay san antonio")
        assert brgy == "San Antonio"

    def test_alias_amlan(self, provider):
        area, brgy = provider._detect_location("outage in ayuquitan")
        assert area == "Amlan"

    def test_alias_bindoy(self, provider):
        area, brgy = provider._detect_location("no power in payabon")
        assert area == "Bindoy"

    def test_alias_valencia(self, provider):
        area, brgy = provider._detect_location("blackout in luzuriaga")
        assert area == "Valencia"

    def test_all_25_lgus_recognized(self, provider):
        for lgu in REQUIRED_LGUS:
            area, _ = provider._detect_location(f"outage in {lgu.lower()}")
            assert area == lgu, f"Failed to detect {lgu}"


class TestFacebookIntegration:
    @pytest.fixture
    def provider(self):
        provider = FacebookProvider()
        provider.collector = MagicMock()
        provider.collector.collect = AsyncMock(return_value=[])
        return provider

    @patch("app.providers.facebook.settings")
    async def test_post_to_signal_conversion(self, mock_settings, provider):
        mock_settings.facebook_enabled = True
        mock_settings.get_facebook_sources.return_value = [
            {"name": "NORECO II", "page_id": "NORECO2Official", "enabled": True}
        ]
        provider.collector.collect.return_value = [{
            "source": "facebook",
            "source_id": "post123",
            "page_id": "NORECO2Official",
            "author": "NORECO II",
            "message": "Brownout diri sa Siaton, 3 hours na walay kuryente",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "url": "https://facebook.com/post123",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {},
        }]

        signals = await provider.fetch_signals()
        assert len(signals) == 1
        assert signals[0]["area"] == "Siaton"
        assert signals[0]["status"] == "out"
        assert signals[0]["score"] >= 5

    @patch("app.providers.facebook.settings")
    async def test_restoration_post_does_not_create_outage_signal(self, mock_settings, provider):
        mock_settings.facebook_enabled = True
        mock_settings.get_facebook_sources.return_value = [
            {"name": "NORECO II", "page_id": "NORECO2Official", "enabled": True}
        ]
        provider.collector.collect.return_value = [{
            "source": "facebook",
            "source_id": "post456",
            "page_id": "NORECO2Official",
            "author": "NORECO II",
            "message": "Nibalik na ang kuryente sa Siaton",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "url": "https://facebook.com/post456",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {},
        }]

        signals = await provider.fetch_signals()
        assert len(signals) == 1
        assert signals[0]["status"] == "restored"

    @patch("app.providers.facebook.settings")
    async def test_disabled_facebook_returns_no_signals(self, mock_settings, provider):
        mock_settings.facebook_enabled = False
        mock_settings.get_facebook_sources.return_value = []

        signals = await provider.fetch_signals()
        assert signals == []
        provider.collector.collect.assert_not_called()


class TestTimezonePresentation:
    def test_utc_to_pht_conversion(self):
        utc = datetime(2026, 9, 4, 11, 32, 36, tzinfo=timezone.utc)
        ph_time = utc.astimezone(PHT)
        assert ph_time.day == 4
        assert ph_time.month == 9
        assert ph_time.year == 2026
        assert ph_time.hour == 19
        assert ph_time.minute == 32
        assert ph_time.second == 36

    def test_utc_date_rollover(self):
        utc = datetime(2026, 9, 4, 23, 30, 0, tzinfo=timezone.utc)
        ph_time = utc.astimezone(PHT)
        assert ph_time.day == 5
        assert ph_time.hour == 7
        assert ph_time.minute == 30