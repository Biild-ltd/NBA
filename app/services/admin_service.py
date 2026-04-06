"""Admin service — member directory, stats, status management, and audit logging.

All Supabase operations are sync helpers called via asyncio.to_thread() so that
the FastAPI async event loop is never blocked.
"""
import asyncio
import csv
import io
import logging
import secrets
import string

from fastapi import HTTPException, UploadFile, status

from app.config import settings
from app.db.supabase import get_service_client
from app.models.profile import ProfileCreate
from app.services import photo_service, qr_service, storage_service

logger = logging.getLogger(__name__)

_SORT_FIELDS = {"created_at", "full_name", "branch"}


# ── Sync DB helpers ────────────────────────────────────────────────────────────

def _get_stats() -> dict:
    client = get_service_client()
    table = client.table("member_profiles")

    total = table.select("id", count="exact").execute().count or 0
    active = table.select("id", count="exact").eq("status", "active").execute().count or 0
    pending = table.select("id", count="exact").eq("status", "pending").execute().count or 0
    suspended = table.select("id", count="exact").eq("status", "suspended").execute().count or 0
    paid = table.select("id", count="exact").eq("payment_status", "paid").execute().count or 0
    unpaid = table.select("id", count="exact").eq("payment_status", "unpaid").execute().count or 0

    latest_row = (
        table.select("full_name, created_at")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    latest_member = None
    if latest_row.data:
        r = latest_row.data[0]
        latest_member = {"full_name": r["full_name"], "created_at": str(r["created_at"])}

    branch_rows = table.select("branch").execute()
    branch_counts: dict[str, int] = {}
    for row in branch_rows.data or []:
        b = row["branch"]
        branch_counts[b] = branch_counts.get(b, 0) + 1
    members_by_branch = [
        {"branch": b, "count": c}
        for b, c in sorted(branch_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "total_members": total,
        "active_members": active,
        "pending_members": pending,
        "suspended_members": suspended,
        "paid_members": paid,
        "unpaid_members": unpaid,
        "latest_member": latest_member,
        "members_by_branch": members_by_branch,
    }


def _list_members(
    q: str | None,
    status_filter: str | None,
    branch: str | None,
    year_of_call: int | None,
    payment_status: str | None,
    start: int,
    end: int,
    sort_by: str,
    desc: bool,
) -> tuple[list[dict], int]:
    query = get_service_client().table("member_profiles").select("*", count="exact")
    if q:
        query = query.or_(
            f"full_name.ilike.%{q}%,branch.ilike.%{q}%,enrollment_no.ilike.%{q}%"
        )
    if status_filter:
        query = query.eq("status", status_filter)
    if branch:
        query = query.eq("branch", branch)
    if year_of_call is not None:
        query = query.eq("year_of_call", year_of_call)
    if payment_status:
        query = query.eq("payment_status", payment_status)
    result = query.range(start, end).order(sort_by, desc=desc).execute()
    return result.data or [], result.count or 0


def _get_member(member_id: str) -> dict | None:
    result = (
        get_service_client()
        .table("member_profiles")
        .select("*")
        .eq("id", member_id)
        .execute()
    )
    return result.data[0] if result.data else None


def _get_member_payments(member_id: str) -> list[dict]:
    result = (
        get_service_client()
        .table("payment_transactions")
        .select("*")
        .eq("member_id", member_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def _update_member(member_id: str, fields: dict) -> dict:
    result = (
        get_service_client()
        .table("member_profiles")
        .update(fields)
        .eq("id", member_id)
        .execute()
    )
    return result.data[0]


def _insert_audit(
    admin_id: str,
    action: str,
    target_id: str,
    old_value: dict | None,
    new_value: dict | None,
) -> None:
    get_service_client().table("admin_audit_log").insert(
        {
            "admin_id": admin_id,
            "action": action,
            "target_id": target_id,
            "old_value": old_value,
            "new_value": new_value,
        }
    ).execute()


def _get_audit_log(start: int, end: int) -> tuple[list[dict], int]:
    result = (
        get_service_client()
        .table("admin_audit_log")
        .select("*", count="exact")
        .range(start, end)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or [], result.count or 0


def _get_all_members(
    status_filter: str | None,
    branch: str | None,
    payment_status: str | None,
) -> list[dict]:
    query = get_service_client().table("member_profiles").select("*")
    if status_filter:
        query = query.eq("status", status_filter)
    if branch:
        query = query.eq("branch", branch)
    if payment_status:
        query = query.eq("payment_status", payment_status)
    return query.order("created_at", desc=True).execute().data or []


def _get_by_uid(member_uid: str) -> dict | None:
    result = (
        get_service_client()
        .table("member_profiles")
        .select("*")
        .eq("member_uid", member_uid)
        .execute()
    )
    return result.data[0] if result.data else None


def _insert_profile(record: dict) -> dict:
    result = get_service_client().table("member_profiles").insert(record).execute()
    return result.data[0]


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


def _generate_member_uid() -> str:
    chars = string.ascii_uppercase + string.digits
    part1 = "".join(secrets.choice(chars) for _ in range(6))
    part2 = "".join(secrets.choice(chars) for _ in range(8))
    return f"NBA-{part1}-{part2}"


# ── Async public API ───────────────────────────────────────────────────────────

async def get_stats() -> dict:
    return await asyncio.to_thread(_get_stats)


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
    start = (page - 1) * page_size
    end = start + page_size - 1
    return await asyncio.to_thread(
        _list_members, q, status_filter, branch, year_of_call, payment_status,
        start, end, sort_by, sort_dir == "desc",
    )


async def get_member_detail(member_id: str) -> dict:
    profile = await asyncio.to_thread(_get_member, member_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")
    payments = await asyncio.to_thread(_get_member_payments, member_id)
    return {**profile, "payment_history": payments}


async def update_status(
    admin_id: str,
    member_id: str,
    new_status: str,
    reason: str | None,
) -> dict:
    profile = await asyncio.to_thread(_get_member, member_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")
    old_status = profile["status"]
    updated = await asyncio.to_thread(_update_member, member_id, {"status": new_status})
    await asyncio.to_thread(
        _insert_audit,
        admin_id,
        "status_change",
        member_id,
        {"status": old_status},
        {"status": new_status, "reason": reason},
    )
    return updated


async def regenerate_qr(admin_id: str, member_id: str) -> str | None:
    profile = await asyncio.to_thread(_get_member, member_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")
    url = await qr_service.generate_and_store(member_id)
    await asyncio.to_thread(
        _insert_audit,
        admin_id,
        "qr_regenerated",
        member_id,
        None,
        {"qr_code_url": url},
    )
    return url


async def get_vcard(member_id: str) -> str:
    profile = await asyncio.to_thread(_get_member, member_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")
    return _format_vcard(profile)


async def export_csv(
    status_filter: str | None = None,
    branch: str | None = None,
    payment_status: str | None = None,
) -> str:
    members = await asyncio.to_thread(_get_all_members, status_filter, branch, payment_status)
    return _format_csv(members)


async def get_audit_log(page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    page_size = min(page_size, 200)
    start = (page - 1) * page_size
    end = start + page_size - 1
    return await asyncio.to_thread(_get_audit_log, start, end)


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
    for _ in range(5):
        uid = _generate_member_uid()
        if not await asyncio.to_thread(_get_by_uid, uid):
            break
    else:
        raise HTTPException(status_code=500, detail="INTERNAL_ERROR")

    profile_url = f"{settings.PUBLIC_BASE_URL}/profile/{uid}"

    record = {
        "id": member_id,
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
        "status": "active",
        "payment_status": "paid",
    }

    try:
        row = await asyncio.to_thread(_insert_profile, record)
    except Exception as exc:
        msg = str(exc).lower()
        if "duplicate" in msg or "unique" in msg:
            if "enrollment_no" in msg:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="DUPLICATE_ENROLLMENT")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A profile already exists for this account.",
            )
        logger.error("Admin profile insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="INTERNAL_ERROR")

    asyncio.create_task(qr_service.generate_and_store(member_id))
    return row
