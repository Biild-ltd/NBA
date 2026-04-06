"""Supabase Storage service.

Handles upload and signed-URL generation for passport photos and QR codes.
All Supabase SDK calls are synchronous and wrapped with asyncio.to_thread().
"""
import asyncio
import logging
import uuid

from app.db.supabase import get_service_client

logger = logging.getLogger(__name__)

BUCKET = "member-assets"

# ~7 years — effectively permanent for the lifetime of a membership card
_SIGNED_URL_EXPIRY_SECONDS = 220_752_000


# ── Sync helpers ──────────────────────────────────────────────────────────────

def _upload(path: str, data: bytes, content_type: str) -> None:
    get_service_client().storage.from_(BUCKET).upload(
        path=path,
        file=data,
        file_options={"content-type": content_type, "upsert": "true"},
    )


def _signed_url(path: str) -> str:
    result = get_service_client().storage.from_(BUCKET).create_signed_url(
        path=path,
        expires_in=_SIGNED_URL_EXPIRY_SECONDS,
    )
    # supabase-py v2 returns a dict with key "signedURL"
    if isinstance(result, dict):
        return result.get("signedURL") or result.get("signed_url", "")
    return str(result)


# ── Async public API ──────────────────────────────────────────────────────────

async def upload_photo(member_id: str, data: bytes, content_type: str) -> str:
    """Upload a passport photo and return a long-lived signed URL.

    Storage path: photos/{member_id}/{uuid}.(jpg|png)
    """
    extension = "jpg" if "jpeg" in content_type else "png"
    path = f"photos/{member_id}/{uuid.uuid4()}.{extension}"
    await asyncio.to_thread(_upload, path, data, content_type)
    return await asyncio.to_thread(_signed_url, path)


async def upload_qr(member_id: str, data: bytes) -> str:
    """Upload (or overwrite) a member's QR code PNG and return a signed URL.

    Storage path: qrcodes/{member_id}/qr.png
    """
    path = f"qrcodes/{member_id}/qr.png"
    await asyncio.to_thread(_upload, path, data, "image/png")
    return await asyncio.to_thread(_signed_url, path)
