from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import NamedTuple, Optional

from pydantic_settings import BaseSettings


class ResultsBackupConfig(NamedTuple):
    """
    Every setting needed to back a result up to a second bucket and
    schedule the primary bucket's copy for deletion -- returned as one
    bundle by Settings.results_backup_config() so callers (storage.py)
    never have to check each field individually. See that method's
    docstring for the fail-safe contract.
    """
    backup_bucket_name: str
    primary_ttl_minutes: int
    cloud_tasks_project: str
    cloud_tasks_location: str
    cloud_tasks_queue: str
    cloud_tasks_service_account_email: str
    cloud_tasks_worker_url: str


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

    # ── Results backup + auto-cleanup (optional) ────────────────────────────────
    # When every setting in this block is present, each uploaded asset is
    # ALSO written to gcs_backup_bucket_name -- same relative path with the
    # leading "VTON/" stripped (e.g. VTON/2026-.../result_0.png ->
    # 2026-.../result_0.png; Mohammad's spec, 2026-09-24: no VTON folder in
    # the backup bucket) -- and the PRIMARY bucket's copy is deleted
    # results_primary_ttl_minutes after upload, via a Cloud Task scheduled
    # to fire at that exact time (see app/cloud_tasks_cleanup.py). The
    # backup bucket's copy is never deleted by this backend -- it's meant
    # to be permanent.
    #
    # GCS's own bucket lifecycle rules can't do this: the minimum age
    # granularity for a native lifecycle rule is whole days, not minutes
    # (confirmed via cloud.google.com/storage/docs/lifecycle, 2026-09-24),
    # so a plain lifecycle rule on the primary bucket can't hit a 15-minute
    # window -- hence the Cloud Tasks-based delayed single-object delete
    # instead.
    #
    # cloud_tasks_worker_url is this service's own full URL for its
    # /internal/cleanup-object route (e.g.
    # https://backend-vertex-xxx-uc.a.run.app/internal/cleanup-object) --
    # used both as the Cloud Task's target and as the OIDC audience it
    # verifies, exactly the same convention API Gateway's
    # CLOUD_TASKS_WORKER_URL already uses for its own internal worker route.
    #
    # Fails safe, not open: leave any one of these unset and every upload
    # behaves exactly as before -- single bucket, permanent storage, no
    # scheduled deletion. All-or-nothing deliberately: a half-configured
    # state (backup writes happening but no deletion scheduled, say)
    # would leave permanent duplicates piling up in the PRIMARY bucket
    # too, defeating "temporary" for that copy.
    gcs_backup_bucket_name: Optional[str] = None
    results_primary_ttl_minutes: int = 15
    cloud_tasks_project: Optional[str] = None
    cloud_tasks_location: Optional[str] = None
    cloud_tasks_cleanup_queue: Optional[str] = None
    cloud_tasks_service_account_email: Optional[str] = None
    cloud_tasks_worker_url: Optional[str] = None

    # ── Server ─────────────────────────────────────────────────────────────────
    # Thread pool size for blocking Vertex AI calls
    worker_threads: int = 8

    # ── Helpers ────────────────────────────────────────────────────────────────
    def results_backup_config(self) -> Optional[ResultsBackupConfig]:
        """Returns the full backup+cleanup bundle if every required setting
        above is present, else None -- see that settings block's own
        docstring for the fail-safe contract storage.py relies on."""
        if not (
            self.gcs_backup_bucket_name
            and self.cloud_tasks_project
            and self.cloud_tasks_location
            and self.cloud_tasks_cleanup_queue
            and self.cloud_tasks_service_account_email
            and self.cloud_tasks_worker_url
        ):
            return None
        return ResultsBackupConfig(
            backup_bucket_name=self.gcs_backup_bucket_name,
            primary_ttl_minutes=self.results_primary_ttl_minutes,
            cloud_tasks_project=self.cloud_tasks_project,
            cloud_tasks_location=self.cloud_tasks_location,
            cloud_tasks_queue=self.cloud_tasks_cleanup_queue,
            cloud_tasks_service_account_email=self.cloud_tasks_service_account_email,
            cloud_tasks_worker_url=self.cloud_tasks_worker_url,
        )

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
