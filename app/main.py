"""
Virtual Try-On API — Google Vertex AI backend.
Designed to run on Google Cloud Run.

Endpoints:
  GET  /health  — liveness / readiness probe
  POST /tryon   — run virtual try-on, upload assets to GCS, return URLs
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Union

import requests as http_requests
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from . import storage
from .cloud_tasks_cleanup import verify_cloud_tasks_oidc
from .config import get_settings
from .vertex import run_tryon, run_tryon_gemini
from .storage import upload_generation
from .imaging import MAX_COMBINED_GARMENTS, combine_images_horizontal

logging.basicConfig(
    level=logging.INFO,
    format="%(filename)-20s:%(lineno)-4d %(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
_executor = ThreadPoolExecutor(max_workers=settings.worker_threads)

# ── Model registry ────────────────────────────────────────────────────────────

DEFAULT_MODEL        = "virtual-try-on-001"
SUPPORTED_MODELS     = frozenset({"virtual-try-on-001", "gemini-3.1-flash-image"})
# Both models now support multiple garments, via two different mechanisms:
# gemini-3.1-flash-image takes each garment natively as its own separate
# reference image; virtual-try-on-001's recontext_image API only accepts one
# product image, so main.py composites multiple garments into a single
# left-to-right photo first (see app/imaging.py) — same approach as the
# FLUX and FASHN backends.
MULTI_GARMENT_MODELS = frozenset({"gemini-3.1-flash-image", "virtual-try-on-001"})

# Optional hint on the request: which body region/category the garment being
# tried on belongs to. Same 9-value vocabulary as the gateway and every other
# VTO backend (see API Gateway's app/config.py:GARMENT_TYPES) — kept in sync
# by hand across repos, same pattern as storage.py/imaging.py.
#
# virtual-try-on-001 has no prompt channel at all (see app/vertex.py's
# _call_via_sdk/_call_via_rest — the request is just personImage +
# productImages, nothing else), so garment_type is silently ignored for it —
# see _pipeline below. gemini-3.1-flash-image IS prompt-driven, so
# garment_type is appended to GEMINI_VTO_PROMPT via run_tryon_gemini —
# including the 4 accessory categories (glasses/shoes/headwear/accessories),
# which now have their own entries in vertex.py's _GARMENT_TYPE_DESCRIPTIONS.
GARMENT_TYPES = frozenset(
    {
        "upper_body",
        "lower_body",
        "dress",
        "full_body",
        "outerwear",
        "glasses",
        "shoes",
        "headwear",
        "accessories",
    }
)

app = FastAPI(
    title="Virtual Try-On — Vertex AI",
    description=(
        "Sends a person + garment image to **Google Vertex AI `virtual-try-on-001`**, "
        "stores all assets in Google Cloud Storage, and returns the result URLs."
    ),
    version="1.0.0",
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class TryOnRequest(BaseModel):
    model_image_url:    str                               = Field(...,            description="Public URL of the person / model image.")
    garment_image_url:  Optional[str]                     = Field(None,           description="[Legacy] Single garment URL. Prefer garment_image_urls.")
    garment_image_urls: Optional[Union[str, list[str]]]   = Field(None,           description=f"Single garment URL (string) or list of garment URLs. Takes priority over garment_image_url. Both models support multiple garments: gemini-3.1-flash-image takes each as a separate native reference image (no cap); virtual-try-on-001 composites them into a single photo first (up to {MAX_COMBINED_GARMENTS} garments).")
    sample_count:       int                               = Field(1, ge=1, le=4, description="Number of result images to generate (1–4). Applies to virtual-try-on-001 only.")
    output_format:      str                               = Field("png",          description="Output image format: 'png' or 'jpeg'.")
    model:              str                               = Field(DEFAULT_MODEL,  description="Model to use. Supported: virtual-try-on-001, gemini-3.1-flash-image.")
    garment_type:       Optional[str]                      = Field(None,           description=f"Optional hint: which body region/category the garment belongs to. One of: {sorted(GARMENT_TYPES)}. Ignored by virtual-try-on-001 (no prompt channel); injected into the prompt for gemini-3.1-flash-image.")

    @field_validator("garment_type")
    @classmethod
    def _validate_garment_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in GARMENT_TYPES:
            raise ValueError(f"Unsupported garment_type '{v}'. Must be one of: {sorted(GARMENT_TYPES)}, or omitted.")
        return v


class TryOnResponse(BaseModel):
    generation_id: str = Field(..., description="Unique ID for this generation.")
    folder:        str = Field(..., description="GCS folder path: VTON/{model}/{generation_id}")
    model_url:     str = Field(..., description="GCS URL of the uploaded person image.")
    garment_url:   str = Field(..., description="GCS URL of the uploaded garment image.")
    result_urls:   list[str] = Field(..., description="GCS URLs of the generated try-on result(s).")


# ── Image loading ─────────────────────────────────────────────────────────────

def _download_image(url: str, label: str) -> Image.Image:
    logger.info("Downloading %s from %s …", label, url)
    try:
        resp = http_requests.get(url, timeout=30)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not load {label} from URL: {exc}")


# ── Core pipeline (sync — runs in thread pool) ────────────────────────────────

def _pipeline(req: TryOnRequest) -> dict:
    cfg = get_settings()

    # 1. Validate model
    if req.model not in SUPPORTED_MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported model '{req.model}'. Supported: {sorted(SUPPORTED_MODELS)}.",
        )

    # Resolve garment field: garment_image_urls takes priority; fall back to legacy garment_image_url
    raw = req.garment_image_urls if req.garment_image_urls is not None else req.garment_image_url
    if raw is None:
        raise HTTPException(status_code=422, detail="Provide garment_image_urls (or the legacy garment_image_url).")
    garment_urls = [raw] if isinstance(raw, str) else list(raw)
    extra_urls   = garment_urls[1:]

    if extra_urls and req.model not in MULTI_GARMENT_MODELS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Model '{req.model}' does not support multiple garments. "
                "Use 'gemini-3.1-flash-image' or 'virtual-try-on-001' for multi-garment try-on."
            ),
        )
    if req.model == DEFAULT_MODEL and len(garment_urls) > MAX_COMBINED_GARMENTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"At most {MAX_COMBINED_GARMENTS} garment images are supported for "
                f"'{DEFAULT_MODEL}' (received {len(garment_urls)})."
            ),
        )

    # 2. Download images
    person_img  = _download_image(req.model_image_url, "person/model image")
    garment_img = _download_image(garment_urls[0],     "garment image")
    extra_imgs  = [
        _download_image(url, f"garment image {i + 2}")
        for i, url in enumerate(extra_urls)
    ]

    # 3. Inference
    # Which extra garment images (if any) get uploaded separately in step 4 —
    # only meaningful for gemini's native-multi-reference path; overridden to
    # [] below for virtual-try-on-001 once its garments are composited.
    upload_extra_garments = extra_imgs

    if req.model == DEFAULT_MODEL:
        # virtual-try-on-001's recontext_image call accepts exactly one
        # product image — when more than one garment was supplied, composite
        # them into a single left-to-right photo first (see app/imaging.py),
        # same approach as the FLUX and FASHN backends. A single garment
        # passes through unchanged. req.garment_type is intentionally ignored
        # here — recontext_image has no prompt/text channel at all (just
        # personImage + productImages), so there's nowhere to put it.
        garment_img = combine_images_horizontal([garment_img] + extra_imgs)
        upload_extra_garments = []  # already folded into the composite above

        logger.info(
            "Vertex AI inference | model=%s samples=%d garments=%d …",
            req.model, req.sample_count, 1 + len(extra_imgs),
        )
        result_images = run_tryon(
            person_image=person_img,
            garment_image=garment_img,
            number_of_images=req.sample_count,
            credentials_dict=cfg.credentials_dict(),
            project=cfg.gcp_project_id,
            location=cfg.gcp_location,
        )
        if not result_images:
            raise HTTPException(status_code=500, detail="Vertex AI returned no images.")

    else:
        all_garments = [garment_img] + extra_imgs
        logger.info("Gemini inference | model=%s garments=%d …", req.model, len(all_garments))
        result_images = run_tryon_gemini(
            person_image=person_img,
            garment_images=all_garments,
            credentials_dict=cfg.credentials_dict(),
            project=cfg.gcp_project_id,
            location=cfg.gcp_location,
            garment_type=req.garment_type,
        )
        if not result_images:
            raise HTTPException(status_code=500, detail="Gemini returned no images.")

    # 4. Upload everything to GCS. For virtual-try-on-001, garment_img is now
    # the composite actually sent to Vertex (or the single original garment,
    # unchanged, if there was only one) — the individual originals aren't
    # persisted separately when there was more than one, same convention as
    # the FLUX/FASHN backends. For gemini, garment_img is still just the
    # first garment, with the rest uploaded via upload_extra_garments.
    bundle = upload_generation(
        model_image=person_img,
        garment_image=garment_img,
        extra_garment_images=upload_extra_garments,
        result_images=result_images,
        bucket_name=cfg.gcs_bucket_name,
        public=cfg.gcs_public_bucket,
        credentials_dict=cfg.credentials_dict(),
        fmt=req.output_format,
        model_folder=req.model,
        backup=cfg.results_backup_config(),
    )
    return bundle


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", summary="Health check")
def health() -> dict:
    return {"status": "ok"}


@app.post("/internal/cleanup-object", include_in_schema=False)
async def cleanup_object(request: Request) -> dict:
    """
    Worker route for the optional results-backup feature's delayed
    delete (see app/config.py's Settings.results_backup_config() and
    app/cloud_tasks_cleanup.py) -- deletes one object from the PRIMARY
    bucket, called only by a Cloud Task this service itself scheduled.
    Never meant to be called by a real client directly; excluded from the
    OpenAPI schema and OIDC-verified below, same pattern as API Gateway's
    own internal worker route.
    """
    verify_cloud_tasks_oidc(
        request.headers.get("authorization"),
        service_account_email=settings.cloud_tasks_service_account_email,
        worker_url=settings.cloud_tasks_worker_url,
    )
    body = await request.json()
    storage.delete_object(
        bucket_name=body["bucket"],
        blob_name=body["name"],
        credentials_dict=settings.credentials_dict(),
    )
    return {"status": "ok"}


@app.post(
    "/tryon",
    response_model=TryOnResponse,
    summary="Run virtual try-on",
    response_description="GCS URLs for the generated try-on result(s) and the uploaded source images.",
)
async def tryon(req: TryOnRequest) -> JSONResponse:
    """
    1. Downloads the person and garment images from the provided URLs.
    2. Calls **Vertex AI `virtual-try-on-001`** to generate the try-on result.
    3. Uploads the person image, garment image, and all result images to GCS:
       - `VTON/{generation_id}/model.png`
       - `VTON/{generation_id}/garment.png`
       - `VTON/{generation_id}/result_0.png`  (… result_1.png if sample_count > 1)
    4. Returns the GCS URLs.
    """
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, lambda: _pipeline(req))
    return JSONResponse(result)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="info")
