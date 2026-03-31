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
from typing import Optional

import requests as http_requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, Field

from .config import get_settings
from .vertex import run_tryon
from .storage import upload_generation

logging.basicConfig(
    level=logging.INFO,
    format="%(filename)-20s:%(lineno)-4d %(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
_executor = ThreadPoolExecutor(max_workers=settings.worker_threads)

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
    model_image_url:   str = Field(..., description="Public URL of the person / model image.")
    garment_image_url: str = Field(..., description="Public URL of the garment / product image.")
    sample_count:      int = Field(1, ge=1, le=4, description="Number of result images to generate (1–4).")
    output_format:     str = Field("png", description="Output image format: 'png' or 'jpeg'.")


class TryOnResponse(BaseModel):
    generation_id: str = Field(..., description="Unique ID for this generation.")
    folder:        str = Field(..., description="GCS folder path: VTON/{generation_id}")
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

    # 1. Download images
    person_img  = _download_image(req.model_image_url,   "person/model image")
    garment_img = _download_image(req.garment_image_url, "garment image")

    # 2. Vertex AI inference
    logger.info("Vertex AI inference | samples=%d …", req.sample_count)
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

    # 3. Upload everything to GCS
    bundle = upload_generation(
        model_image=person_img,
        garment_image=garment_img,
        result_images=result_images,
        bucket_name=cfg.gcs_bucket_name,
        public=cfg.gcs_public_bucket,
        credentials_dict=cfg.credentials_dict(),
        fmt=req.output_format,
    )
    return bundle


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", summary="Health check")
def health() -> dict:
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
