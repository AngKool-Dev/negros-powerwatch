import pytest
from fastapi.testclient import TestClient

from app.main import app


class TestHealth:
    def test_api_prefix(self, client):
        response = client.get("/api/v1/status")
        assert response.status_code == 200


class TestStatus:
    def test_get_status(self, client):
        response = client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "active_outages" in data
        assert "last_updated" in data


class TestOutages:
    def test_get_outages_empty(self, client):
        response = client.get("/api/v1/outages")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_active_outages_empty(self, client):
        response = client.get("/api/v1/outages/active")
        assert response.status_code == 200
        assert response.json() == []


class TestReports:
    def test_submit_power_off_report(self, client):
        response = client.post(
            "/api/v1/reports",
            json={
                "power_status": "off",
                "latitude": 9.8,
                "longitude": 123.5,
                "municipality": "Siaton",
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "report_id" in data

    def test_duplicate_report_rejected(self, client):
        response1 = client.post(
            "/api/v1/reports",
            json={"power_status": "off", "session_id": "test-session-1"}
        )
        assert response1.status_code == 200

        response2 = client.post(
            "/api/v1/reports",
            json={"power_status": "off", "session_id": "test-session-1"}
        )
        assert response2.status_code == 429

    def test_submit_power_restored(self, client):
        client.post(
            "/api/v1/reports",
            json={"power_status": "off", "session_id": "test-session-restore"}
        )
        response = client.post(
            "/api/v1/reports",
            json={"power_status": "restored", "session_id": "test-session-restore"}
        )
        assert response.status_code == 200

    def test_report_validation(self, client):
        response = client.post(
            "/api/v1/reports",
            json={"power_status": "invalid"}
        )
        assert response.status_code == 422
