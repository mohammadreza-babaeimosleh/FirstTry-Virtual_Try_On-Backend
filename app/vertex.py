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
        config   = types.RecontextImageConfig(number_of_images=number_of_images,
            safety_filter_level=types.SafetyFilterLevel.BLOCK_ONLY_HIGH)
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
        "parameters": {
            "sampleCount": number_of_images,
            "safetySetting": "block-only-high"  
        },
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


# ── Gemini image-generation VTO ───────────────────────────────────────────────

GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"

GEMINI_VTO_PROMPT = (
    "You are a Virtual Try-On system. You are given a model image and one or more "
    "garment image(s). Your task is to realistically dress the model in the provided "
    "garment(s).\n\n"
    "The following rules MUST be strictly obeyed:\n\n"
    "1. **Preserve the model exactly**\n"
    "   * Keep the model's face, identity, facial expression, skin tone, hair, body "
    "shape, body proportions, age, gender presentation, and pose exactly as they "
    "appear in the model image.\n"
    "   * Keep visible features such as hands, legs, tattoos, makeup, jewelry, and "
    "accessories exactly as they appear, except where the garment physically covers "
    "them.\n\n"
    "2. **Preserve the pose**\n"
    "   * Accurately recognize the model's body pose, posture, limb positions, and camera angle.\n"
    "   * The garment must follow the model's existing pose naturally.\n"
    "   * Keep the model's body in its exact original position, orientation, and proportions.\n\n"
    "3. **Preserve the garment exactly**\n"
    "   * Keep the garment's color, texture, fabric type, pattern, logos, stitching, seams, "
    "buttons, zippers, prints, embroidery, and all visible design details exactly as they "
    "appear in the garment image(s).\n"
    "   * Reproduce every garment detail faithfully and at full clarity — sharp, accurate, "
    "and true to the source.\n"
    "   * The garment should retain its original style, silhouette, length, fit, and structure "
    "while conforming naturally to the model's body and pose.\n\n"
    "4. **Preserve the scene**\n"
    "   * Keep the background, lighting, shadows, camera perspective, image framing, and "
    "environment exactly as they appear in the model image.\n"
    "   * Keep every object already in the scene exactly as it appears.\n\n"
    "5. **Realistic integration**\n"
    "   * The garment must be placed only on the correct body area.\n"
    "   * Respect natural occlusions, such as arms, hair, hands, bags, or other objects "
    "appearing in front of the clothing.\n"
    "   * Adjust wrinkles, folds, and shadows only as needed to make the garment look naturally "
    "worn, while preserving the garment's original appearance.\n"
    "   * The final result must look photorealistic and seamless.\n\n"
    "6. **Faithful, unedited output**\n"
    "   * Include only the clothing, accessories, body parts, logos, text, patterns, and "
    "background elements already present in the source images.\n"
    "   * Keep the image quality, resolution, aspect ratio, and composition exactly as in "
    "the model image.\n"
    "   * Render the result as a straight photorealistic photograph, matching the medium of "
    "the source images.\n\n"
    "Your output should be the original model image with only the provided garment(s) realistically "
    "worn by the model."
)


# Natural-language description of each garment_type value, used to build the
# extra instruction line appended to GEMINI_VTO_PROMPT when a caller passes
# garment_type. Keep the keys in sync with main.py's GARMENT_TYPES (and the
# gateway's — see API Gateway's app/config.py:GARMENT_TYPES).
_GARMENT_TYPE_DESCRIPTIONS: dict[str, str] = {
    "upper_body": "an upper-body garment such as a top, shirt, blouse, or jacket worn as the main upper layer",
    "lower_body": "a lower-body garment such as pants, trousers, or a skirt",
    "dress": "a dress",
    "full_body": "a full-body garment or outfit covering both the upper and lower body",
    "outerwear": "an outerwear layer such as a coat, jacket, or cardigan worn over other clothing",
    "glasses": "a pair of glasses (eyewear), such as sunglasses or prescription frames, worn on the face",
    "shoes": "a pair of shoes or other footwear, worn on the feet",
    "headwear": "a headwear item such as a hat, cap, or beanie, worn on the head",
    "accessories": "an accessory item such as a bag, belt, scarf, tie, or piece of jewelry",
}


def _garment_type_instruction(garment_type: Optional[str]) -> Optional[str]:
    """Extra prompt line for a known garment_type, or None if not provided/unrecognized."""
    if not garment_type:
        return None
    description = _GARMENT_TYPE_DESCRIPTIONS.get(garment_type)
    if description is None:
        return None
    return (
        f"\n\nThe garment being applied from the garment image(s) is {description}. If a "
        "garment image itself shows more than one garment (for example, a coordinated "
        "set photographed together), take only this specified garment from it, "
        "independent of every other garment or item visible in that image. Use this to "
        "correctly identify which item and body region on the person to replace."
    )


def run_tryon_gemini(
    person_image:     Image.Image,
    garment_images:   list[Image.Image],
    credentials_dict: Optional[dict] = None,
    project:          str = "",
    location:         str = "us-central1",
    garment_type:     Optional[str] = None,
) -> list[Image.Image]:
    """
    Call gemini-3.1-flash-image via Vertex AI for multi-garment virtual try-on.
    Accepts one person image and one or more garment images.
    Returns a list containing the single result PIL Image.

    `garment_type`, when provided, is appended to the prompt as an extra
    instruction line (see _garment_type_instruction) — a hint for which body
    region/category the garment belongs to, e.g. to disambiguate a garment
    image that shows a full outfit rather than an isolated item.
    """
    creds  = _service_account_creds(credentials_dict)
    client = genai.Client(
        vertexai=True,
        project=project,
        location=location,
        credentials=creds,
    )

    prompt = GEMINI_VTO_PROMPT
    extra = _garment_type_instruction(garment_type)
    if extra:
        prompt += extra

    parts = [
        types.Part.from_bytes(data=_pil_to_bytes(person_image), mime_type="image/png"),
        *(types.Part.from_bytes(data=_pil_to_bytes(g), mime_type="image/png") for g in garment_images),
        types.Part.from_text(text=prompt),
    ]

    response = client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    result_images = []
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if getattr(part, "inline_data", None):
                result_images.append(
                    Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
                )
    return result_images
