"""
Delayed single-object deletion via Cloud Tasks -- the mechanism behind the
optional results-backup feature (see app/config.py's
Settings.results_backup_config()). When enabled, storage.py schedules one
of these tasks per uploaded object, timed to fire exactly
primary_ttl_minutes after upload and delete that one object from the
PRIMARY bucket only -- the backup bucket's copy is never touched here, by
design (it's meant to be permanent).

Same OIDC-verification pattern as API Gateway's app/services/cloud_tasks.py
+ app/routers/internal_tasks.py: this service has both public routes and
one internal worker route (/internal/cleanup-object, app/main.py) on the
same Cloud Run service, so Cloud Run's own service-level "require
authentication" IAM gate can't be used here without also locking out every
public route. Instead every task scheduled here carries an OIDC token
signed for cloud_tasks_service_account_email with the worker route's own
URL as audience; app/main.py verifies that token itself at the application
layer. This is Google's documented pattern for a Cloud Tasks target that
isn't its own dedicated, IAM-gated Cloud Run service.

Unlike API Gateway's pacing queues (which dispatch immediately and rely on
each queue's own max-dispatches-per-second setting for pacing -- see that
repo's app/services/cloud_tasks.py), this queue has no external rate
constraint to pace against; deleting from GCS isn't capped by anything.
schedule_time is set explicitly on each task instead, so it fires once, at
one precise future time, rather than being paced by the queue.

Everything here runs synchronously and is called from storage.py's
_upload(), which itself already runs off the main event loop (inside
main.py's ThreadPoolExecutor, via _run_in_executor) -- so, unlike the
Gateway's async cloud_tasks.py, there's no need for asyncio.to_thread
here; a direct blocking SDK call is already off the loop that matters.
"""
from __future__ import annotations

import datetime
import json
import logging
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.cloud import tasks_v2
from google.oauth2 import id_token
from google.protobuf import timestamp_pb2

from .config import ResultsBackupConfig

logger = logging.getLogger(__name__)


class CloudTasksError(Exception):
    """Raised when scheduling a delete task fails."""


@lru_cache(maxsize=1)
def _client() -> tasks_v2.CloudTasksClient:
    return tasks_v2.CloudTasksClient()


def schedule_delete(bucket_name: str, blob_name: str, backup: ResultsBackupConfig) -> None:
    """
    Schedule a Cloud Task that deletes gs://{bucket_name}/{blob_name} (the
    PRIMARY bucket's copy only) exactly backup.primary_ttl_minutes from
    now. Raises CloudTasksError on failure -- storage.py logs and
    continues rather than failing the whole upload over it, since the
    backup copy already exists regardless; a scheduling failure just means
    this one primary-bucket object won't be auto-deleted.
    """
    client = _client()
    parent = client.queue_path(backup.cloud_tasks_project, backup.cloud_tasks_location, backup.cloud_tasks_queue)

    run_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=backup.primary_ttl_minutes)
    schedule_time = timestamp_pb2.Timestamp()
    schedule_time.FromDatetime(run_at)

    task = {
        "schedule_time": schedule_time,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": backup.cloud_tasks_worker_url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"bucket": bucket_name, "name": blob_name}).encode(),
            "oidc_token": {
                "service_account_email": backup.cloud_tasks_service_account_email,
                "audience": backup.cloud_tasks_worker_url,
            },
        },
    }
    try:
        client.create_task(parent=parent, task=task)
    except Exception as exc:
        raise CloudTasksError(f"Failed to schedule delete for gs://{bucket_name}/{blob_name}: {exc}") from exc


def verify_cloud_tasks_oidc(authorization: Optional[str], *, service_account_email: str, worker_url: str) -> None:
    """
    Raises HTTPException(401/403) unless `authorization` is a valid Google
    OIDC bearer token, issued with `worker_url` as audience, and signed by
    `service_account_email` specifically. Mirrors API Gateway's
    app/routers/internal_tasks.py::_verify_cloud_tasks_oidc exactly --
    called from app/main.py's /internal/cleanup-object route.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        claims = id_token.verify_oauth2_token(token, google_requests.Request(), audience=worker_url)
    except Exception as exc:
        logger.warning("Rejected internal cleanup request: invalid OIDC token (%s)", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc

    if claims.get("email") != service_account_email:
        logger.warning(
            "Rejected internal cleanup request: token signed by unexpected account %s", claims.get("email"),
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unexpected signer.")
