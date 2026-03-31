from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Google Cloud ───────────────────────────────────────────────────────────
    # Full JSON string of a GCP service account key.
    # Leave unset on Cloud Run when using a dedicated service account (ADC).
    gcs_credentials_json: Optional[str] = None

    gcp_project_id: str
    gcp_location:   str = "us-central1"

    # ── GCS storage ────────────────────────────────────────────────────────────
    gcs_bucket_name: str

    # true  → return public  https:// URLs  (bucket must have allUsers read)
    # false → return signed  https:// URLs  (valid 1 h, private bucket OK)
    gcs_public_bucket: bool = False

    # ── Server ─────────────────────────────────────────────────────────────────
    # Thread pool size for blocking Vertex AI calls
    worker_threads: int = 8

    # ── Helpers ────────────────────────────────────────────────────────────────
    def credentials_dict(self) -> Optional[dict]:
        """Return the service account dict, or None (→ use ADC)."""
        raw = self.gcs_credentials_json
        if not raw:
            return None
        raw = raw.strip()
        # Support env vars that contain the JSON as a file path
        if raw.startswith("/") and os.path.isfile(raw):
            with open(raw) as fh:
                return json.load(fh)
        return json.loads(raw)

    class Config:
        env_file = ".env"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
