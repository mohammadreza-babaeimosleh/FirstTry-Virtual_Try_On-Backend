"""
Image compositing helper for multi-garment virtual-try-on-001 requests.

virtual-try-on-001's underlying Vertex AI `recontext_image` API accepts
exactly one product image per call (see app/vertex.py:_call_via_sdk /
_call_via_rest — `product_images=[types.ProductImage(...)]`, always a single
entry). When a request supplies more than one garment_image_url, main.py
composites them into a single left-to-right photo with
combine_images_horizontal() below rather than rejecting the request — the
same approach already used by the FLUX and FASHN backends
(backend_api_flux_vto_gcp/app/imaging.py, backend_api_flux_klein_gcp/app/
imaging.py, backend_api_fashn_gcp/app/imaging.py) for models whose API also
only takes one garment image. gemini-3.1-flash-image is unaffected — it
takes each garment natively as its own separate reference image and never
calls this function.
"""
from __future__ import annotations

from PIL import Image

# A photo-legibility cap, not a provider API limit — keeps each garment
# legible in the resulting composite strip and the payload size reasonable.
# Same value as the other three backends' MAX_COMBINED_GARMENTS.
MAX_COMBINED_GARMENTS = 6


def combine_images_horizontal(
    images: list[Image.Image], *, gap: int = 8, background: tuple[int, int, int] = (255, 255, 255)
) -> Image.Image:
    """
    Composite multiple garment images into a single photo: each is resized to
    the tallest image's height (preserving aspect ratio — the smaller ones are
    upscaled rather than shrinking everyone down to the smallest, so no
    garment loses visible detail), then placed left to right on a plain
    background with a small gap between them.

    Returns the input unchanged if there's only one image. Callers are
    expected to enforce MAX_COMBINED_GARMENTS before calling this — it does
    not check the count itself.
    """
    if not images:
        raise ValueError("combine_images_horizontal requires at least one image.")
    if len(images) == 1:
        return images[0]

    target_height = max(img.height for img in images)
    resized = []
    for img in images:
        scale = target_height / img.height
        new_width = max(1, round(img.width * scale))
        resized.append(img.resize((new_width, target_height), Image.LANCZOS))

    total_width = sum(img.width for img in resized) + gap * (len(resized) - 1)
    canvas = Image.new("RGB", (total_width, target_height), background)
    x = 0
    for img in resized:
        canvas.paste(img, (x, 0))
        x += img.width + gap
    return canvas
