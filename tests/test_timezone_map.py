import json
import os
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.engine import OutageEngine
from app.models import GeographicArea, CommunityReport

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

PHT = ZoneInfo("Asia/Manila")


class TestTimezone:
    def test_api_timestamps_are_iso8601_utc(self, client):
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert "Z" in data["last_updated"] or "+" in data["last_updated"]

    def test_philippine_date_boundary(self, client, db):
        area = GeographicArea(name="TestArea", area_type="municipality", latitude=9.8, longitude=123.5)
        db.add(area)
        db.flush()

        utc_boundary = datetime(2026, 9, 4, 16, 59, tzinfo=timezone.utc)
        report = CommunityReport(
            session_id="tz-test",
            timestamp=utc_boundary,
            latitude=9.8,
            longitude=123.5,
            area_id=area.id,
            power_status="off",
        )
        db.add(report)
        db.commit()

        engine = OutageEngine(db)
        engine.process_community_report(report)
        db.commit()

        response = client.get("/api/v1/outages/active")
        assert response.status_code == 200
        outages = response.json()
        assert len(outages) >= 1

    def test_last_updated_is_not_server_boot_time(self, client):
        import time
        time.sleep(1)
        r1 = client.get("/api/v1/status")
        data1 = r1.json()
        time.sleep(1)
        r2 = client.get("/api/v1/status")
        data2 = r2.json()
        assert data1["last_updated"] != data2["last_updated"]

    def test_outage_duration_independent_of_timezone(self, client, db):
        area = GeographicArea(name="DurationTest", area_type="municipality", latitude=9.8, longitude=123.5)
        db.add(area)
        db.flush()

        start = datetime(2026, 9, 4, 11, 13, 4, tzinfo=timezone.utc)
        end = datetime(2026, 9, 4, 11, 49, 36, tzinfo=timezone.utc)
        expected_duration = 36 * 60 + 32

        r1 = CommunityReport(
            session_id="dur-test-1",
            timestamp=start,
            latitude=9.8,
            longitude=123.5,
            area_id=area.id,
            power_status="off",
        )
        db.add(r1)
        db.flush()

        r2 = CommunityReport(
            session_id="dur-test-2",
            timestamp=end,
            latitude=9.8,
            longitude=123.5,
            area_id=area.id,
            power_status="restored",
        )
        db.add(r2)
        db.commit()

        engine = OutageEngine(db)
        engine.process_community_report(r1)
        engine.process_community_report(r2)
        db.commit()

        response = client.get("/api/v1/outages/active")
        outages = response.json()
        assert len(outages) >= 1
        outage = outages[0]
        assert outage["started_at"] is not None
        assert outage["restored_at"] is not None
        started = datetime.fromisoformat(outage["started_at"].replace("Z", "+00:00"))
        restored = datetime.fromisoformat(outage["restored_at"].replace("Z", "+00:00"))
        duration = (restored - started).total_seconds()
        assert abs(duration - expected_duration) < 2


class TestFrontendTimezone:
    def test_timezone_module_exists(self):
        tz_path = os.path.join(STATIC_DIR, "js", "timezone.js")
        assert os.path.exists(tz_path), "Centralized timezone module missing"

    def test_timezone_module_exports_asia_manila(self):
        tz_path = os.path.join(STATIC_DIR, "js", "timezone.js")
        with open(tz_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Asia/Manila" in content, "timezone.js must export Asia/Manila"

    def test_utc_to_ph_conversion(self):
        utc = datetime(2026, 9, 4, 11, 32, 36, tzinfo=timezone.utc)
        ph_time = utc.astimezone(PHT)
        formatted = ph_time.strftime("%B %d, %Y, %I:%M:%S %p").replace(" 0", " ")
        assert "September" in formatted
        assert "7:32:36 PM" in formatted

    def test_utc_date_rollover(self):
        utc = datetime(2026, 9, 4, 23, 30, 0, tzinfo=timezone.utc)
        ph_time = utc.astimezone(PHT)
        assert ph_time.day == 5, "Date should roll over to next day in PHT"
        assert ph_time.hour == 7, "23:30 UTC should be 07:30 PHT"
        assert ph_time.minute == 30

    def test_templates_use_centralized_timezone(self):
        for filename in ["index.html", "map.html", "outages.html", "outage_detail.html"]:
            path = os.path.join(TEMPLATES_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "timezone.js" in content, f"{filename} missing timezone.js import"
            bare_locale = re.findall(r'toLocale(?:Time|String)\([^)]*\)(?!\s*\{)', content)
            for call in bare_locale:
                assert "timeZone" in call or "Asia/Manila" in call, \
                    f"{filename} has bare locale call without timeZone: {call}"


class TestMapGeometry:
    def test_all_25_lgus_present_in_geojson(self):
        geojson_path = os.path.join(STATIC_DIR, "geojson", "municipalities.geojson")
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        names = {feat["properties"]["name"] for feat in data["features"]}
        for lgu in REQUIRED_LGUS:
            assert lgu in names, f"Missing LGU: {lgu}"
        assert len(names) == 25, f"Expected 25 features, got {len(names)}"

    def test_siaton_geometry_is_polygon_or_multipolygon(self):
        geojson_path = os.path.join(STATIC_DIR, "geojson", "municipalities.geojson")
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        siaton = next(f for f in data["features"] if f["properties"]["name"] == "Siaton")
        geom_type = siaton["geometry"]["type"]
        assert geom_type in ("Polygon", "MultiPolygon"), f"Siaton is {geom_type}"
        coords = siaton["geometry"]["coordinates"]
        if geom_type == "Polygon":
            assert len(coords[0]) > 4, "Siaton polygon has too few vertices for real boundary"

    def test_no_rectangle_geometry_in_geojson(self):
        geojson_path = os.path.join(STATIC_DIR, "geojson", "municipalities.geojson")
        with open(geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for feat in data["features"]:
            coords = feat["geometry"]["coordinates"]
            if feat["geometry"]["type"] == "Polygon":
                ring = coords[0]
                lons = [c[0] for c in ring]
                lats = [c[1] for c in ring]
                unique_lons = len(set(round(l, 2) for l in lons))
                unique_lats = len(set(round(l, 2) for l in lats))
                assert unique_lons > 2 or unique_lats > 2, \
                    f"{feat['properties']['name']} looks like a rectangle"

    def test_siaton_outage_does_not_spill_to_neighbors(self, client, db):
        siaton = GeographicArea(name="Siaton", area_type="municipality", latitude=9.65, longitude=123.15)
        zamb = GeographicArea(name="Zamboanguita", area_type="municipality", latitude=9.10, longitude=123.20)
        db.add_all([siaton, zamb])
        db.flush()

        report = CommunityReport(
            session_id="map-test",
            timestamp=datetime.now(timezone.utc),
            latitude=9.65,
            longitude=123.15,
            area_id=siaton.id,
            power_status="off",
        )
        db.add(report)
        db.commit()

        engine = OutageEngine(db)
        engine.process_community_report(report)
        db.commit()

        response = client.get("/api/v1/map/status")
        assert response.status_code == 200
        areas = response.json()
        names = [a["area_name"] for a in areas]
        assert "Siaton" in names
        assert "Zamboanguita" not in names

    def test_multiple_outages_are_independent_polygons(self, client, db):
        siaton = GeographicArea(name="Siaton", area_type="municipality", latitude=9.65, longitude=123.15)
        zamb = GeographicArea(name="Zamboanguita", area_type="municipality", latitude=9.10, longitude=123.20)
        db.add_all([siaton, zamb])
        db.flush()

        reports = []
        for sid, aid in [("multi-1", siaton.id), ("multi-2", zamb.id)]:
            r = CommunityReport(
                session_id=sid,
                timestamp=datetime.now(timezone.utc),
                latitude=9.65 if sid == "multi-1" else 9.10,
                longitude=123.15 if sid == "multi-1" else 123.20,
                area_id=aid,
                power_status="off",
            )
            db.add(r)
            db.flush()
            reports.append(r)
        db.commit()

        engine = OutageEngine(db)
        for r in reports:
            engine.process_community_report(r)
        db.commit()

        response = client.get("/api/v1/map/status")
        areas = response.json()
        names = sorted([a["area_name"] for a in areas])
        assert names == ["Siaton", "Zamboanguita"]

    def test_map_template_uses_outage_markers_not_rectangles(self):
        map_path = os.path.join(TEMPLATES_DIR, "map.html")
        with open(map_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "outageMarkerLayer" in content, "Map must use outage marker layer"
        assert "circleMarker" in content, "Map must use circle markers for outage indication"
        assert "L.rectangle" not in content, "Map must not use L.rectangle for outage zones"
        assert "L.polygon" not in content, "Map must not manually create outage polygons"
