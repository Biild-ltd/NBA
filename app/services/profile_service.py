"""Profile service — member profile CRUD and member_uid generation.

Photo validation (Stage 1 + Stage 2) is delegated to photo_service.
"""
import asyncio
import logging
import secrets
import string

from fastapi import HTTPException, UploadFile, status

from app.config import settings
from app.db.supabase import get_service_client
from app.models.profile import ProfileCreate, ProfileUpdate
from app.services import photo_service, storage_service

logger = logging.getLogger(__name__)


# ── member_uid generation ─────────────────────────────────────────────────────

def generate_member_uid() -> str:
    """Generate a unique NBA member ID: NBA-XXXXXX-XXXXXXXX."""
    chars = string.ascii_uppercase + string.digits
    part1 = "".join(secrets.choice(chars) for _ in range(6))
    part2 = "".join(secrets.choice(chars) for _ in range(8))
    return f"NBA-{part1}-{part2}"


# ── Sync DB helpers ───────────────────────────────────────────────────────────

def _insert_profile(record: dict) -> dict:
    result = get_service_client().table("member_profiles").insert(record).execute()
    return result.data[0]


def _get_by_id(user_id: str) -> dict | None:
    result = (
        get_service_client()
        .table("member_profiles")
        .select("*")
        .eq("id", user_id)
        .execute()
    )
    return result.data[0] if result.data else None


def _get_by_uid(member_uid: str) -> dict | None:
    result = (
        get_service_client()
        .table("member_profiles")
        .select("*")
        .eq("member_uid", member_uid)
        .execute()
    )
    return result.data[0] if result.data else None


def _update(user_id: str, fields: dict) -> dict:
    result = (
        get_service_client()
        .table("member_profiles")
        .update(fields)
        .eq("id", user_id)
        .execute()
    )
    return result.data[0]


# ── Async public API ──────────────────────────────────────────────────────────

async def create_profile(
    user_id: str,
    data: ProfileCreate,
    photo: UploadFile,
) -> dict:
    # Read photo bytes and run full two-stage validation pipeline
    photo_bytes = await photo.read()
    mime = photo_service.validate_photo_stage1(photo_bytes)  # raises 422 on Stage 1 failure
    stage2 = await photo_service.validate_photo_stage2(photo_bytes, mime)
    if not stage2.passed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "PHOTO_REJECTED",
                "message": "Your photo did not pass compliance checks.",
                "details": {"failures": stage2.failures, "score": stage2.score},
            },
        )

    # Generate a collision-free member_uid (extremely unlikely to collide)
    for _ in range(5):
        uid = generate_member_uid()
        if not await asyncio.to_thread(_get_by_uid, uid):
            break
    else:
        raise HTTPException(status_code=500, detail="INTERNAL_ERROR")

    photo_url = await storage_service.upload_photo(user_id, photo_bytes, mime)
    profile_url = f"{settings.PUBLIC_BASE_URL}/profile/{uid}"

    record = {
        "id": user_id,
        "full_name": data.full_name,
        "enrollment_no": data.enrollment_no,
        "year_of_call": data.year_of_call,
        "branch": data.branch,
        "phone_number": data.phone_number,
        "email_address": str(data.email_address),
        "office_address": data.office_address,
        "photo_url": photo_url,
        "member_uid": uid,
        "profile_url": profile_url,
    }

    try:
        row = await asyncio.to_thread(_insert_profile, record)
    except Exception as exc:
        msg = str(exc).lower()
        if "duplicate" in msg or "unique" in msg:
            if "enrollment_no" in msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="DUPLICATE_ENROLLMENT",
                )
            if "member_profiles_pkey" in msg or "profiles" in msg:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A profile already exists for this account.",
                )
        logger.error("Profile insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="INTERNAL_ERROR")

    return row


async def get_my_profile(user_id: str) -> dict:
    row = await asyncio.to_thread(_get_by_id, user_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )
    return row


async def get_public_profile(member_uid: str) -> dict:
    """Public lookup — only returns active profiles (for QR scan landing pages)."""
    row = await asyncio.to_thread(_get_by_uid, member_uid)
    if not row or row.get("status") != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )
    return row


async def update_my_profile(
    user_id: str,
    data: ProfileUpdate,
    photo: UploadFile | None = None,
) -> dict:
    existing = await asyncio.to_thread(_get_by_id, user_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )

    updates = data.model_dump(exclude_none=True)

    if photo is not None:
        photo_bytes = await photo.read()
        mime = photo_service.validate_photo_stage1(photo_bytes)  # raises 422 on Stage 1 failure
        stage2 = await photo_service.validate_photo_stage2(photo_bytes, mime)
        if not stage2.passed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "PHOTO_REJECTED",
                    "message": "Your photo did not pass compliance checks.",
                    "details": {"failures": stage2.failures, "score": stage2.score},
                },
            )
        updates["photo_url"] = await storage_service.upload_photo(
            user_id, photo_bytes, mime
        )

    if not updates:
        return existing

    return await asyncio.to_thread(_update, user_id, updates)
