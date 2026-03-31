"""
Test script for backend_api_vertex_gcp.

Usage:
  # Test against local Docker container
  python test_api.py

  # Test against deployed Cloud Run service
  BASE_URL=https://your-service-url.run.app python test_api.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080").rstrip("/")
BASE_URL = "https://vton-api-234062011057.us-central1.run.app"

# ── Inputs — replace with real publicly accessible image URLs ──────────────────

# MODEL_IMAGE_URL:   "https://6174co.com/wp-content/uploads/2026/02/5866172930130119565.jpg",
MODEL_IMAGE_URL = "https://6174co.com/wp-content/uploads/2026/03/5872825671262866644.jpg"

# GARMENT_IMAGE_URL: "https://6174co.com/wp-content/uploads/2026/02/5868487290437438321.jpg",
GARMENT_IMAGE_URL = "https://beams-america.com/cdn/shop/files/Copyof010563803_79.webp?v=1750197156&width=1100"

PAYLOAD = {
    "model_image_url":   MODEL_IMAGE_URL,
    "garment_image_url": GARMENT_IMAGE_URL,
    "sample_count":      1,       # 1–4
    "output_format":     "png",   # "png" or "jpeg"
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _post(path: str, body: dict) -> dict:
    data    = json.dumps(body).encode()
    req     = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10) as resp:
        return json.loads(resp.read())


def _download(url: str, dest: str) -> None:
    urllib.request.urlretrieve(url, dest)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health() -> None:
    print("── Health check ──────────────────────────────────────")
    result = _get("/health")
    assert result.get("status") == "ok", f"Unexpected: {result}"
    print("  OK:", result)


def test_tryon() -> None:
    print("\n── POST /tryon ───────────────────────────────────────")
    print("  Payload:", json.dumps(PAYLOAD, indent=4))

    t0     = time.time()
    result = _post("/tryon", PAYLOAD)
    elapsed = time.time() - t0

    print(f"\n  Completed in {elapsed:.1f}s")
    print("  generation_id :", result.get("generation_id"))
    print("  folder        :", result.get("folder"))
    print("  model_url     :", result.get("model_url"))
    print("  garment_url   :", result.get("garment_url"))
    print("  result_urls   :", result.get("result_urls"))

    # Download result images
    result_urls = result.get("result_urls", [])
    if not result_urls:
        print("\n  WARNING: no result URLs returned.")
        return

    os.makedirs("output_images", exist_ok=True)
    for i, url in enumerate(result_urls):
        dest = f"output_images/result_{i}.png"
        print(f"\n  Downloading result {i} → {dest} …")
        _download(url, dest)
        print(f"  Saved: {dest}")

    print("\n  Done.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Target: {BASE_URL}\n")
    try:
        test_health()
        test_tryon()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"\nHTTP {exc.code}: {exc.reason}")
        try:
            print(json.dumps(json.loads(body), indent=2))
        except Exception:
            print(body)
        sys.exit(1)
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
