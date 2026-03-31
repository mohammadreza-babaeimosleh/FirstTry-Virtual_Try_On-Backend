"""
Vertex AI Virtual Try-On client.

Uses the google-genai SDK (recontext_image) as the primary call path.
Falls back to a direct REST request if the SDK is unavailable or fails.

Officially documented parameters:
  number_of_images (SDK) / sampleCount (REST)  — 1–4 images to generate
"""
from __future__ import annotations

import base64
import io
import json
import logging
from typing import Optional
import requests
from PIL import Image

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

MODEL_ID = "virtual-try-on-001"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pil_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _service_account_creds(credentials_dict: Optional[dict]):
    """Build a google-auth Credentials object from a service account dict, or return None (ADC)."""
    if not credentials_dict:
        return None
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(
        credentials_dict,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


# ── SDK path ──────────────────────────────────────────────────────────────────

def _call_via_sdk(
    person_image:     Image.Image,
    garment_image:    Image.Image,
    number_of_images: int,
    credentials_dict: Optional[dict],
    project:          str,
    location:         str,
) -> list[Image.Image]:


    creds  = _service_account_creds(credentials_dict)
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location,
        credentials=creds,
    )

    person_bytes  = _pil_to_bytes(person_image)
    garment_bytes = _pil_to_bytes(garment_image)

    source = types.RecontextImageSource(
        person_image=types.Image(image_bytes=person_bytes),
        product_images=[
            types.ProductImage(product_image=types.Image(image_bytes=garment_bytes))
        ],
    )

    try:
        config   = types.RecontextImageConfig(number_of_images=number_of_images)
        response = client.models.recontext_image(model=MODEL_ID, source=source, config=config)
    except (AttributeError, TypeError) as exc:
        logger.warning("RecontextImageConfig unavailable (%s) — using default (1 image).", exc)
        response = client.models.recontext_image(model=MODEL_ID, source=source)

    return [
        Image.open(io.BytesIO(g.image.image_bytes)).convert("RGB")
        for g in response.generated_images
    ]


# ── REST fallback ─────────────────────────────────────────────────────────────

def _call_via_rest(
    person_image:     Image.Image,
    garment_image:    Image.Image,
    number_of_images: int,
    credentials_dict: Optional[dict],
    project:          str,
    location:         str,
) -> list[Image.Image]:
    # Obtain an access token
    creds = _service_account_creds(credentials_dict)
    if creds is None:
        import google.auth
        import google.auth.transport.requests
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    if not creds.valid:
        import google.auth.transport.requests
        creds.refresh(google.auth.transport.requests.Request())

    token = creds.token

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1"
        f"/projects/{project}/locations/{location}"
        f"/publishers/google/models/{MODEL_ID}:predict"
    )
    payload = {
        "instances": [{
            "person_image":   {"bytesBase64Encoded": _b64(_pil_to_bytes(person_image))},
            "product_images": [{"bytesBase64Encoded": _b64(_pil_to_bytes(garment_image))}],
        }],
        "parameters": {"sampleCount": number_of_images},
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()

    images = []
    for prediction in data.get("predictions", []):
        b64_data = prediction.get("bytesBase64Encoded") or prediction.get("image", {}).get("bytesBase64Encoded")
        if b64_data:
            images.append(Image.open(io.BytesIO(base64.b64decode(b64_data))).convert("RGB"))
    return images


# ── Public API ────────────────────────────────────────────────────────────────

def run_tryon(
    person_image:     Image.Image,
    garment_image:    Image.Image,
    number_of_images: int = 1,
    credentials_dict: Optional[dict] = None,
    project:          str = "",
    location:         str = "us-central1",
) -> list[Image.Image]:
    """
    Call Vertex AI virtual-try-on-001.
    Returns a list of result PIL Images.
    """
    # Try SDK first
    try:
        import google.genai  # noqa: F401
        logger.info("Calling Vertex AI via google-genai SDK …")
        return _call_via_sdk(
            person_image, garment_image, number_of_images,
            credentials_dict, project, location,
        )
    except ImportError:
        logger.info("google-genai SDK not available — falling back to REST.")
    except Exception as exc:
        logger.warning("SDK call failed (%s) — falling back to REST.", exc)

    logger.info("Calling Vertex AI via REST …")
    return _call_via_rest(
        person_image, garment_image, number_of_images,
        credentials_dict, project, location,
    )
