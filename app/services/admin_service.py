"""Admin service — member directory, stats, status management, and audit logging.

All DB operations use asyncpg directly.
"""
import asyncio
import csv
import io
import logging
import secrets
import string

import asyncpg
from fastapi import HTTPException, status

from app.config import settings
from app.db.postgres import get_pool
from app.models.profile import ProfileCreate
from app.services import photo_service, qr_service, storage_service

logger = logging.getLogger(__name__)

_SORT_FIELDS = {"created_at", "full_name", "branch"}


# ── Async public API ───────────────────────────────────────────────────────────

async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        counts = await conn.fetchrow(
            """SELECT
               COUNT(*)                                          AS total,
               COUNT(*) FILTER (WHERE status = 'active')        AS active_count,
               COUNT(*) FILTER (WHERE status = 'pending')       AS pending_count,
               COUNT(*) FILTER (WHERE status = 'suspended')     AS suspended_count,
               COUNT(*) FILTER (WHERE payment_status = 'paid')  AS paid_count,
               COUNT(*) FILTER (WHERE payment_status = 'unpaid') AS unpaid_count
               FROM public.member_profiles"""
        )
        latest_row = await conn.fetchrow(
            "SELECT full_name, created_at FROM public.member_profiles ORDER BY created_at DESC LIMIT 1"
        )
        branch_rows = await conn.fetch(
            "SELECT branch, COUNT(*) AS cnt FROM public.member_profiles GROUP BY branch ORDER BY cnt DESC"
        )

    latest_member = None
    if latest_row:
        latest_member = {
            "full_name": latest_row["full_name"],
            "created_at": str(latest_row["created_at"]),
        }

    return {
        "total_members": counts["total"],
        "active_members": counts["active_count"],
        "pending_members": counts["pending_count"],
        "suspended_members": counts["suspended_count"],
        "paid_members": counts["paid_count"],
        "unpaid_members": counts["unpaid_count"],
        "latest_member": latest_member,
        "members_by_branch": [
            {"branch": r["branch"], "count": r["cnt"]} for r in branch_rows
        ],
    }


async def list_members(
    q: str | None = None,
    status_filter: str | None = None,
    branch: str | None = None,
    year_of_call: int | None = None,
    payment_status: str | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
) -> tuple[list[dict], int]:
    page_size = min(page_size, 200)
    if sort_by not in _SORT_FIELDS:
        sort_by = "created_at"
    offset = (page - 1) * page_size
    order = "DESC" if sort_dir == "desc" else "ASC"

    conditions: list[str] = []
    params: list = []
    idx = 1

    if q:
        conditions.append(
            f"(full_name ILIKE ${idx} OR branch ILIKE ${idx} OR enrollment_no ILIKE ${idx})"
        )
        params.append(f"%{q}%")
        idx += 1
    if status_filter:
        conditions.append(f"status = ${idx}")
        params.append(status_filter)
        idx += 1
    if branch:
        conditions.append(f"branch = ${idx}")
        params.append(branch)
        idx += 1
    if year_of_call is not None:
        conditions.append(f"year_of_call = ${idx}")
        params.append(year_of_call)
        idx += 1
    if payment_status:
        conditions.append(f"payment_status = ${idx}")
        params.append(payment_status)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([page_size, offset])

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM public.member_profiles {where} "
            f"ORDER BY {sort_by} {order} LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
        )
        total_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS cnt FROM public.member_profiles {where}",
            *params[:-2],  # exclude LIMIT/OFFSET params
        )

    return [dict(r) for r in rows], total_row["cnt"]


async def get_member_detail(member_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM public.member_profiles WHERE id = $1",
            member_id,
        )
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")
        payments = await conn.fetch(
            "SELECT * FROM public.payment_transactions WHERE member_id = $1 ORDER BY created_at DESC",
            member_id,
        )

    return {**dict(profile), "payment_history": [dict(p) for p in payments]}


async def update_status(
    admin_id: str,
    member_id: str,
    new_status: str,
    reason: str | None,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM public.member_profiles WHERE id = $1",
            member_id,
        )
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")

        old_status = profile["status"]

        async with conn.transaction():
            updated = await conn.fetchrow(
                "UPDATE public.member_profiles SET status = $1 WHERE id = $2 RETURNING *",
                new_status,
                member_id,
            )
            import json
            await conn.execute(
                """INSERT INTO public.admin_audit_log
                   (admin_id, action, target_id, old_value, new_value)
                   VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)""",
                admin_id,
                "status_change",
                member_id,
                json.dumps({"status": old_status}),
                json.dumps({"status": new_status, "reason": reason}),
            )

    return dict(updated)


async def regenerate_qr(admin_id: str, member_id: str) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT id FROM public.member_profiles WHERE id = $1",
            member_id,
        )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")

    url = await qr_service.generate_and_store(member_id)

    import json
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO public.admin_audit_log
               (admin_id, action, target_id, old_value, new_value)
               VALUES ($1, $2, $3, NULL, $4::jsonb)""",
            admin_id,
            "qr_regenerated",
            member_id,
            json.dumps({"qr_code_url": url}),
        )

    return url


async def get_vcard(member_id: str) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM public.member_profiles WHERE id = $1",
            member_id,
        )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")
    return _format_vcard(dict(profile))


async def export_csv(
    status_filter: str | None = None,
    branch: str | None = None,
    payment_status: str | None = None,
) -> str:
    conditions: list[str] = []
    params: list = []
    idx = 1

    if status_filter:
        conditions.append(f"status = ${idx}")
        params.append(status_filter)
        idx += 1
    if branch:
        conditions.append(f"branch = ${idx}")
        params.append(branch)
        idx += 1
    if payment_status:
        conditions.append(f"payment_status = ${idx}")
        params.append(payment_status)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM public.member_profiles {where} ORDER BY created_at DESC",
            *params,
        )

    return _format_csv([dict(r) for r in rows])


async def get_audit_log(page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    page_size = min(page_size, 200)
    offset = (page - 1) * page_size

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM public.admin_audit_log ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            page_size,
            offset,
        )
        total_row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM public.admin_audit_log")

    return [dict(r) for r in rows], total_row["cnt"]


async def create_member(
    member_id: str,
    data: ProfileCreate,
    photo_bytes: bytes | None,
    mime: str | None,
) -> dict:
    """Create a profile for an existing auth user with payment waived (status=active)."""
    photo_url: str | None = None

    if photo_bytes is not None and mime is not None:
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
        photo_url = await storage_service.upload_photo(member_id, photo_bytes, mime)

    # Collision-free member_uid generation
    uid: str | None = None
    for _ in range(5):
        candidate = _generate_member_uid()
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM public.member_profiles WHERE member_uid = $1",
                candidate,
            )
        if not existing:
            uid = candidate
            break
    if uid is None:
        raise HTTPException(status_code=500, detail="INTERNAL_ERROR")

    profile_url = f"{settings.PUBLIC_BASE_URL}/profile/{uid}"

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO public.member_profiles
                   (id, full_name, enrollment_no, year_of_call, branch,
                    phone_number, email_address, office_address,
                    photo_url, member_uid, profile_url, status, payment_status)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                   RETURNING *""",
                member_id,
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
                "active",
                "paid",
            )
        except asyncpg.UniqueViolationError as exc:
            constraint = exc.constraint_name or ""
            if "enrollment_no" in constraint:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="DUPLICATE_ENROLLMENT")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A profile already exists for this account.",
            )
        except Exception as exc:
            logger.error("Admin profile insert failed: %s", exc)
            raise HTTPException(status_code=500, detail="INTERNAL_ERROR")

    asyncio.create_task(qr_service.generate_and_store(member_id))
    return dict(row)


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _generate_member_uid() -> str:
    chars = string.ascii_uppercase + string.digits
    part1 = "".join(secrets.choice(chars) for _ in range(6))
    part2 = "".join(secrets.choice(chars) for _ in range(8))
    return f"NBA-{part1}-{part2}"


def _format_vcard(profile: dict) -> str:
    return (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        f"FN:{profile['full_name']}\r\n"
        "ORG:Nigerian Bar Association\r\n"
        f"TEL;TYPE=CELL:{profile['phone_number']}\r\n"
        f"EMAIL:{profile['email_address']}\r\n"
        f"ADR:;;{profile['office_address']};;;;\r\n"
        f"NOTE:NBA Member - {profile['member_uid']} | Branch: {profile['branch']} | "
        f"Year of Call: {profile['year_of_call']}\r\n"
        "END:VCARD\r\n"
    )


def _format_csv(members: list[dict]) -> str:
    buf = io.StringIO()
    fields = [
        "member_uid", "full_name", "branch", "year_of_call", "enrollment_no",
        "email_address", "phone_number", "status", "payment_status", "created_at",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(members)
    return buf.getvalue()
