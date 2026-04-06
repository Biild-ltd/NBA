"""QR Code generation and storage service.

Flow:
  generate_and_store → called via asyncio.create_task after successful payment webhook;
                       generates QR PNG, uploads to Supabase Storage, updates qr_code_url on profile.
  get_qr_bytes       → called by QR endpoints; generates PNG on-demand from stored profile_url.
"""
import asyncio
import io
import logging

from fastapi import HTTPException, status
from PIL import Image

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from app.db.supabase import get_service_client
from app.services import storage_service

logger = logging.getLogger(__name__)


# ── Sync helpers ───────────────────────────────────────────────────────────────

def _generate_qr_png(profile_url: str) -> bytes:
    """Generate a 400×400 NBA-green QR code PNG and return raw bytes."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(profile_url)
    qr.make(fit=True)
    img_wrapper = qr.make_image(fill_color="#1A5C2A", back_color="#FFFFFF")
    img_resized = img_wrapper.get_image().resize((400, 400), Image.LANCZOS)
    buf = io.BytesIO()
    img_resized.save(buf, format="PNG")
    return buf.getvalue()


def _get_profile_by_id(member_id: str) -> dict | None:
    result = (
        get_service_client()
        .table("member_profiles")
        .select("id, profile_url")
        .eq("id", member_id)
        .maybe_single()
        .execute()
    )
    return result.data


def _get_profile_by_uid(member_uid: str) -> dict | None:
    result = (
        get_service_client()
        .table("member_profiles")
        .select("id, profile_url")
        .eq("member_uid", member_uid)
        .maybe_single()
        .execute()
    )
    return result.data


def _update_qr_url(member_id: str, qr_code_url: str) -> None:
    get_service_client().table("member_profiles").update(
        {"qr_code_url": qr_code_url}
    ).eq("id", member_id).execute()


# ── Async public API ───────────────────────────────────────────────────────────

async def generate_and_store(member_id: str) -> str | None:
    """Generate a QR code PNG, upload to Supabase Storage, and update the profile.

    Non-fatal: all exceptions are caught and logged; returns None on failure.
    Designed to be called via asyncio.create_task() from the payment webhook handler.
    """
    try:
        profile = await asyncio.to_thread(_get_profile_by_id, member_id)
        if not profile:
            logger.warning("QR generation: profile not found for member_id=%s", member_id)
            return None

        png_bytes = await asyncio.to_thread(_generate_qr_png, profile["profile_url"])
        url = await storage_service.upload_qr(member_id, png_bytes)
        await asyncio.to_thread(_update_qr_url, member_id, url)
        logger.info("QR code generated and stored for member_id=%s", member_id)
        return url
    except Exception as exc:
        logger.error("QR generation failed for member_id=%s: %s", member_id, exc)
        return None


async def get_qr_bytes(member_uid: str) -> bytes:
    """Return QR PNG bytes for a member, generated on-demand from their stored profile_url.

    Raises:
        HTTPException 404 — member_uid not found.
    """
    profile = await asyncio.to_thread(_get_profile_by_uid, member_uid)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )
    return await asyncio.to_thread(_generate_qr_png, profile["profile_url"])
