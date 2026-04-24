"""Profile service — member profile CRUD and member_uid generation.

Photo validation (Stage 1 + Stage 2) is delegated to photo_service.
All DB operations use asyncpg directly (no asyncio.to_thread needed).
"""
import asyncio
import logging
import secrets
import string
from datetime import datetime, timezone

import asyncpg
from fastapi import HTTPException, UploadFile, status

from app.config import settings
from app.db.postgres import get_pool
from app.models.profile import ProfileCreate, ProfileUpdate
from app.services import photo_service, qr_service, storage_service

logger = logging.getLogger(__name__)


# ── member_uid generation ─────────────────────────────────────────────────────

def generate_member_uid() -> str:
    """Generate a unique NBA member ID: NBA-XXXXXX-XXXXXXXX."""
    chars = string.ascii_uppercase + string.digits
    part1 = "".join(secrets.choice(chars) for _ in range(6))
    part2 = "".join(secrets.choice(chars) for _ in range(8))
    return f"NBA-{part1}-{part2}"


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _get_by_id(user_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM public.member_profiles WHERE id = $1",
            user_id,
        )
    return dict(row) if row else None


async def _get_by_uid(member_uid: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM public.member_profiles WHERE member_uid = $1",
            member_uid,
        )
    return dict(row) if row else None


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

    # Generate a collision-free member_uid
    for _ in range(5):
        uid = generate_member_uid()
        if not await _get_by_uid(uid):
            break
    else:
        raise HTTPException(status_code=500, detail="INTERNAL_ERROR")

    try:
        photo_url = await storage_service.upload_photo(user_id, photo_bytes, mime)
    except Exception as exc:
        logger.error("Photo storage upload failed for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "STORAGE_ERROR",
                "message": "Photo upload failed. Please try again.",
                "details": {},
            },
        )

    profile_url = f"{settings.PUBLIC_BASE_URL}/profile/{uid}"

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO public.member_profiles
                   (id, full_name, enrollment_no, year_of_call, branch,
                    phone_number, email_address, office_address,
                    photo_url, member_uid, profile_url)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                   RETURNING *""",
                user_id,
                data.full_name,
                data.enrollment_no,
                data.year_of_call,
                data.branch,
                data.phone_number,
                str(data.email_address),
                data.office_address,
                photo_url,
                uid,
                profile_url,
            )
        except asyncpg.UniqueViolationError as exc:
            constraint = exc.constraint_name or ""
            if "enrollment_no" in constraint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="DUPLICATE_ENROLLMENT",
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A profile already exists for this account.",
            )
        except Exception as exc:
            logger.error("Profile insert failed: %s", exc)
            raise HTTPException(status_code=500, detail="INTERNAL_ERROR")

    if settings.BYPASS_PAYMENT:
        ref = f"NBA-FREE-{secrets.token_hex(8).upper()}"
        now = datetime.now(timezone.utc)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO public.payment_transactions
                       (member_id, reference, amount, currency, status, verified_at)
                       VALUES ($1, $2, 0, 'NGN', 'success', $3)""",
                    user_id, ref, now,
                )
                row = await conn.fetchrow(
                    """UPDATE public.member_profiles
                       SET payment_status = 'paid', status = 'active', payment_ref = $1
                       WHERE id = $2 RETURNING *""",
                    ref, user_id,
                )
        asyncio.create_task(qr_service.generate_and_store(user_id))
        logger.info("Payment bypassed on profile creation for user %s", user_id)

    return dict(row)


async def get_my_profile(user_id: str) -> dict:
    row = await _get_by_id(user_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )
    return row


async def get_public_profile(member_uid: str) -> dict:
    """Public lookup — only returns active profiles (for QR scan landing pages)."""
    row = await _get_by_uid(member_uid)
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
    existing = await _get_by_id(user_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )

    updates = data.model_dump(exclude_none=True)

    if photo is not None:
        photo_bytes = await photo.read()
        mime = photo_service.validate_photo_stage1(photo_bytes)
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

    # Build dynamic SET clause
    set_parts = []
    params: list = []
    for i, (key, val) in enumerate(updates.items(), start=1):
        set_parts.append(f"{key} = ${i}")
        params.append(val)
    params.append(user_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.member_profiles SET {', '.join(set_parts)} "
            f"WHERE id = ${len(params)} RETURNING *",
            *params,
        )

    return dict(row)
