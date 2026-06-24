"""
Google Cloud Storage helpers.

All assets for a single generation are stored under one folder:
  VTON/{generation_id}/
    model.png      — original person image
    garment.png    — original garment image
    result_0.png   — first try-on output
    result_1.png   — second output (if sample_count > 1)
    …

URL strategy:
  public=True               → permanent public https:// URL  (bucket must allow allUsers read)
  public=False + SA JSON    → V4 signed URL (1 h) using the private key in the JSON
  public=False + ADC only   → V4 signed URL (1 h) via IAM Credentials API
                              (service account needs roles/iam.serviceAccountTokenCreator on itself)
"""
from __future__ import annotations

import datetime
import io
import logging
import uuid
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)


# ── GCS client ────────────────────────────────────────────────────────────────

def _get_client(credentials_dict: Optional[dict]):
    from google.cloud import storage
    if credentials_dict:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(credentials_dict)
        return storage.Client(project=credentials_dict.get("project_id"), credentials=creds)
    return storage.Client()   # Application Default Credentials (Cloud Run)


# ── Image helpers ─────────────────────────────────────────────────────────────

def _pil_to_bytes(img: Image.Image, fmt: str = "png") -> bytes:
    fmt_map = {"png": "PNG", "jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP"}
    buf = io.BytesIO()
    img.save(buf, format=fmt_map.get(fmt.lower(), "PNG"), optimize=True)
    return buf.getvalue()


def _content_type(fmt: str) -> str:
    return {
        "png": "image/png", "jpeg": "image/jpeg",
        "jpg": "image/jpeg", "webp": "image/webp",
    }.get(fmt.lower(), "image/png")


# ── URL generation ────────────────────────────────────────────────────────────

def _signed_url_via_iam(blob, expiration_hours: int = 1) -> str:
    """
    Generate a V4 signed URL using the IAM Credentials API.
    Works on Cloud Run (ADC / Compute Engine token) without a service account JSON file.

    Requirements:
      - The Cloud Run service account must have
        roles/iam.serviceAccountTokenCreator on *itself*.
    """
    import google.auth
    from google.auth.iam import Signer
    from google.auth.transport import requests as google_requests
    from google.oauth2.service_account import Credentials as SACredentials

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_request = google_requests.Request()
    credentials.refresh(auth_request)

    # Resolve the service account email from the token metadata
    sa_email = getattr(credentials, "service_account_email", None)
    if not sa_email:
        raise RuntimeError(
            "Cannot determine service account email from ADC credentials. "
            "Set GCS_PUBLIC_BUCKET=true or supply GCS_CREDENTIALS_JSON."
        )

    signer = Signer(
        request=auth_request,
        credentials=credentials,
        service_account_email=sa_email,
    )
    signing_creds = SACredentials(
        signer=signer,
        service_account_email=sa_email,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
    )
    return blob.generate_signed_url(
        expiration=datetime.timedelta(hours=expiration_hours),
        credentials=signing_creds,
        method="GET",
        version="v4",
    )


def _get_url(blob, public: bool, has_private_key: bool) -> str:
    """Return the best URL for a blob depending on available credentials."""
    if public:
        return f"https://storage.googleapis.com/{blob.bucket.name}/{blob.name}"

    if has_private_key:
        # Service account JSON available — sign directly with the embedded key
        return blob.generate_signed_url(
            expiration=datetime.timedelta(hours=1),
            method="GET",
            version="v4",
        )

    # Cloud Run ADC — sign via IAM Credentials API
    return _signed_url_via_iam(blob)


# ── Public API ────────────────────────────────────────────────────────────────

def upload_generation(
    model_image:          Image.Image,
    garment_image:        Image.Image,
    result_images:        list[Image.Image],
    bucket_name:          str,
    public:               bool = False,
    credentials_dict:     Optional[dict] = None,
    fmt:                  str = "png",
    extra_garment_images: Optional[list[Image.Image]] = None,
) -> dict:
    """
    Upload all images for one generation to GCS and return their URLs.

    Primary garment → garment.png  (garment_url in response)
    Extra garments  → garment_1.png, garment_2.png, … (saved but not in response)

    Returns:
      {
        "generation_id": str,
        "folder":        "VTON/{id}",
        "model_url":     str,
        "garment_url":   str,
        "result_urls":   [str, …],
      }
    """
    client        = _get_client(credentials_dict)
    has_key       = bool(credentials_dict)
    generation_id = uuid.uuid4().hex
    folder        = f"VTON/{generation_id}"
    mime          = _content_type(fmt)
    ext           = fmt.lower()

    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    def _upload(img: Image.Image, name: str) -> str:
        blob = client.bucket(bucket_name).blob(name)
        blob.metadata = {"created": created_at, "generation_id": generation_id}
        blob.upload_from_string(_pil_to_bytes(img, fmt), content_type=mime)
        if public:
            blob.make_public()
        return _get_url(blob, public=public, has_private_key=has_key)

    extras = extra_garment_images or []
    logger.info(
        "Uploading generation %s to gs://%s/%s … (garments=%d)",
        generation_id, bucket_name, folder, 1 + len(extras),
    )

    model_url   = _upload(model_image,   f"{folder}/model.{ext}")
    garment_url = _upload(garment_image, f"{folder}/garment.{ext}")

    for i, img in enumerate(extras):
        _upload(img, f"{folder}/garment_{i + 1}.{ext}")

    result_urls = [
        _upload(img, f"{folder}/result_{i}.{ext}")
        for i, img in enumerate(result_images)
    ]
    logger.info("Upload complete. %d garment(s), %d result(s).", 1 + len(extras), len(result_urls))

    return {
        "generation_id": generation_id,
        "folder":        folder,
        "model_url":     model_url,
        "garment_url":   garment_url,
        "result_urls":   result_urls,
    }
