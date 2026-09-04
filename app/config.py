from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Dict, Any
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Negros PowerWatch"
    debug: bool = True
    database_url: str = "sqlite:///./powerwatch.db"
    secret_key: str = "dev-secret-key-change-in-production"

    api_v1_prefix: str = "/api/v1"

    report_duplicate_window_seconds: int = 300
    report_min_reports: int = 3
    report_time_window_seconds: int = 600
    report_radius_km: float = 5.0

    stale_signal_seconds: int = 3600
    restoration_window_seconds: int = 300

    sse_retry_interval_ms: int = 5000

    facebook_access_token: str = ""
    facebook_poll_interval_minutes: int = 1
    facebook_sources: str = "[]"
    facebook_enabled: bool = True

    def get_facebook_sources(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.facebook_sources)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_facebook_source_names(self) -> List[str]:
        return [s.get("name", s.get("page_id", s.get("url", "unknown"))) for s in self.get_facebook_sources()]


settings = Settings()
