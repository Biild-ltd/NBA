"""Photo validation service — two-stage passport photo compliance pipeline.

Stage 1: File-level checks (MIME from content, size, dimensions, aspect ratio).
Stage 2: Claude Vision API visual compliance checks (7 rules).
         Results are cached by MD5 hash with a 24-hour TTL in the
         photo_validation_cache Supabase table.
         Falls back to Stage-1-only pass if Claude Vision is unavailable.
"""
import asyncio
import base64
import hashlib
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import magic
from anthropic import Anthropic, APIConnectionError, APIStatusError, APITimeoutError
from fastapi import HTTPException, status
from PIL import Image

from app.config import settings
from app.db.supabase import get_service_client
from app.models.photo import PhotoValidationResult

logger = logging.getLogger(__name__)

_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
_MIN_DIMENSION = 200                 # px
_MIN_ASPECT_RATIO = 3 / 4           # height >= 1.33× width
_ALLOWED_MIMES = {"image/jpeg", "image/png"}
_CACHE_TTL_HOURS = 24

_PHOTO_VALIDATION_PROMPT = """\
You are a passport photo compliance checker for a professional membership organisation.

Analyse this photograph and return ONLY a JSON object (no other text) with this exact structure:
{
  "passed": true | false,
  "score": 0.0 to 1.0,
  "failures": ["failure reason 1", "failure reason 2"]
}

Check these rules — fail on ANY violation:
1. Background must be plain white or very light (no colour, pattern, or busy background)
2. Face must be clearly visible and facing the camera directly
3. No sunglasses or tinted eyewear
4. Must not be a selfie (no visible arm, camera appears at or above eye level)
5. Passport-style framing: head and upper shoulders only, centred
6. No heavy shadows across the face
7. Good, even lighting — not severely over or underexposed

Set "passed" to true only if ALL rules pass. List each failed rule in "failures".\
"""


# ── Stage 1: File-level checks ────────────────────────────────────────────────

def validate_photo_stage1(data: bytes) -> str:
    """Run file-level checks. Returns the detected MIME type on success.

    Raises HTTP 422 with code 'PHOTO_REJECTED' on any failure.
    Collects all failures before raising so callers get a complete list.
    """
    failures: list[str] = []

    # MIME type — detect from content, never trust the file extension
    mime = magic.from_buffer(data, mime=True)
    if mime not in _ALLOWED_MIMES:
        failures.append(f"Unsupported file type '{mime}'. Only JPEG and PNG are accepted.")

    # File size
    if len(data) > _MAX_PHOTO_BYTES:
        failures.append(
            f"File size {len(data) / 1_048_576:.1f} MB exceeds the 5 MB limit."
        )

    # Dimensions and aspect ratio via Pillow
    try:
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w < _MIN_DIMENSION or h < _MIN_DIMENSION:
            failures.append(
                f"Image dimensions {w}×{h}px are too small. Minimum is 200×200px."
            )
        elif h < w * _MIN_ASPECT_RATIO:
            failures.append(
                "Image must have a portrait aspect ratio of at least 3:4 "
                f"(height ≥ 1.33× width). Got {w}×{h}px."
            )
    except Exception:
        failures.append("File could not be read as a valid image.")

    if failures:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "PHOTO_REJECTED",
                "message": "Your photo did not pass file-level checks.",
                "details": {"failures": failures, "score": 0.0},
            },
        )

    return mime


# ── Stage 2 helpers ───────────────────────────────────────────────────────────

def _compute_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _get_cached_result_sync(image_hash: str) -> Optional[dict]:
    """Query photo_validation_cache. Returns result_json dict or None on miss/expiry."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
    ).isoformat()
    resp = (
        get_service_client()
        .table("photo_validation_cache")
        .select("result_json")
        .eq("image_hash", image_hash)
        .gt("created_at", cutoff)
        .maybe_single()
        .execute()
    )
    return resp.data["result_json"] if resp.data else None


def _save_cached_result_sync(image_hash: str, result: PhotoValidationResult) -> None:
    """Upsert validation result into photo_validation_cache."""
    get_service_client().table("photo_validation_cache").upsert(
        {"image_hash": image_hash, "result_json": result.model_dump()}
    ).execute()


def _call_claude_vision(data: bytes, mime_type: str) -> PhotoValidationResult:
    """Synchronous Claude Vision API call — wrapped in asyncio.to_thread by caller."""
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": base64.b64encode(data).decode(),
                        },
                    },
                    {"type": "text", "text": _PHOTO_VALIDATION_PROMPT},
                ],
            }
        ],
    )
    raw_text = response.content[0].text.strip()
    # Strip markdown code fences if the model wraps the JSON
    if raw_text.startswith("```"):
        parts = raw_text.split("```")
        raw_text = parts[1] if len(parts) > 1 else parts[0]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()
    parsed = json.loads(raw_text)
    return PhotoValidationResult(**parsed)


# ── Stage 2: Claude Vision with caching ───────────────────────────────────────

async def validate_photo_stage2(data: bytes, mime_type: str) -> PhotoValidationResult:
    """Run Claude Vision compliance check with MD5 caching and fallback.

    Flow:
      1. Cache hit (within 24 h) → return cached result immediately.
      2. Cache miss → call Claude Vision → cache result → return result.
      3. Claude Vision unavailable → log WARNING, return passed=True
         (Stage 1 gate is still enforced by the caller).
    """
    image_hash = _compute_md5(data)

    # 1. Check cache
    cached_raw = await asyncio.to_thread(_get_cached_result_sync, image_hash)
    if cached_raw is not None:
        logger.debug("Photo validation cache hit for hash %s", image_hash)
        return PhotoValidationResult(**cached_raw)

    # 2. Call Claude Vision
    try:
        result = await asyncio.to_thread(_call_claude_vision, data, mime_type)
    except (APIConnectionError, APITimeoutError, APIStatusError, Exception) as exc:
        logger.warning(
            "Claude Vision unavailable — falling back to Stage 1 only. error=%s", exc
        )
        return PhotoValidationResult(passed=True, score=1.0, failures=[])

    # 3. Cache result (non-critical; log and continue on failure)
    try:
        await asyncio.to_thread(_save_cached_result_sync, image_hash, result)
    except Exception as exc:
        logger.warning("Failed to cache photo validation result: %s", exc)

    return result
