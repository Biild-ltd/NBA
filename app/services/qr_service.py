"""QR Code generation and storage service.

Flow:
  generate_and_store → called via asyncio.create_task after successful payment webhook;
                       generates QR PNG, uploads to GCS, updates qr_code_url on profile.
  get_qr_bytes       → called by QR endpoints; generates PNG on-demand from stored profile_url.

All DB operations use asyncpg directly.
"""
import asyncio
import io
import logging

from fastapi import HTTPException, status
from PIL import Image

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from app.db.postgres import get_pool
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


# ── Async public API ───────────────────────────────────────────────────────────

async def generate_and_store(member_id: str) -> str | None:
    """Generate a QR code PNG, upload to GCS, and update the profile.

    Non-fatal: all exceptions are caught and logged; returns None on failure.
    Designed to be called via asyncio.create_task() from the payment webhook handler.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            profile = await conn.fetchrow(
                "SELECT id, profile_url FROM public.member_profiles WHERE id = $1",
                member_id,
            )

        if not profile:
            logger.warning("QR generation: profile not found for member_id=%s", member_id)
            return None

        png_bytes = await asyncio.to_thread(_generate_qr_png, profile["profile_url"])
        url = await storage_service.upload_qr(member_id, png_bytes)

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.member_profiles SET qr_code_url = $1 WHERE id = $2",
                url,
                member_id,
            )

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
    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT id, profile_url FROM public.member_profiles WHERE member_uid = $1",
            member_uid,
        )

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )
    return await asyncio.to_thread(_generate_qr_png, profile["profile_url"])
