from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError

from app.dependencies import require_admin
from app.models.admin import (
    AdminStatsResponse,
    AuditLogEntry,
    AuditLogResponse,
    EnrollmentUpdateRequest,
    MemberDirectoryResponse,
    AdminMemberSummary,
    StatusUpdateRequest,
)
from app.models.profile import ProfileCreate, ProfileResponse
from app.services import admin_service
from app.services.photo_service import validate_photo_stage1

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── GET /admin/stats ──────────────────────────────────────────────────────────

@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(
    current_user: dict = Depends(require_admin),
) -> AdminStatsResponse:
    """Dashboard stats: member counts by status, payment status, latest member, branch breakdown."""
    data = await admin_service.get_stats()
    return AdminStatsResponse(**data)


# ── GET /admin/members ────────────────────────────────────────────────────────

@router.get("/members", response_model=MemberDirectoryResponse)
async def list_members(
    q: str | None = None,
    status: str | None = None,
    branch: str | None = None,
    year_of_call: int | None = None,
    payment_status: str | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    current_user: dict = Depends(require_admin),
) -> MemberDirectoryResponse:
    """Paginated, filterable member directory."""
    rows, total = await admin_service.list_members(
        q=q,
        status_filter=status,
        branch=branch,
        year_of_call=year_of_call,
        payment_status=payment_status,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    members = [AdminMemberSummary(**r) for r in rows]
    return MemberDirectoryResponse(total=total, page=page, page_size=page_size, members=members)


# ── POST /admin/members ───────────────────────────────────────────────────────

@router.post("/members", response_model=ProfileResponse)
async def create_member(
    member_id: str = Form(...),
    full_name: str = Form(...),
    enrollment_no: str = Form(...),
    year_of_call: int = Form(...),
    branch: str = Form(...),
    phone_number: str = Form(...),
    email_address: str = Form(...),
    office_address: str = Form(...),
    photo: UploadFile | None = File(default=None),
    current_user: dict = Depends(require_admin),
) -> ProfileResponse:
    """Create a member profile with payment waived (sets status=active, payment_status=paid)."""
    try:
        data = ProfileCreate(
            full_name=full_name,
            enrollment_no=enrollment_no,
            year_of_call=year_of_call,
            branch=branch,
            phone_number=phone_number,
            email_address=email_address,
            office_address=office_address,
        )
    except ValidationError as exc:
        errors = [{k: v for k, v in e.items() if k != "ctx"} for e in exc.errors()]
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "One or more input fields are invalid.",
                "details": {"errors": errors},
            },
        )

    photo_bytes: bytes | None = None
    mime: str | None = None
    if photo is not None:
        photo_bytes = await photo.read()
        mime = validate_photo_stage1(photo_bytes)  # raises 422 on Stage 1 failure

    row = await admin_service.create_member(member_id, data, photo_bytes, mime)
    return ProfileResponse(**row)


# ── GET /admin/members/{member_id} ────────────────────────────────────────────

@router.get("/members/{member_id}")
async def get_member_detail(
    member_id: str,
    current_user: dict = Depends(require_admin),
) -> dict:
    """Full member detail including payment history."""
    return await admin_service.get_member_detail(member_id)


# ── PATCH /admin/members/{member_id}/status ───────────────────────────────────

@router.patch("/members/{member_id}/status", response_model=ProfileResponse)
async def update_member_status(
    member_id: str,
    body: StatusUpdateRequest,
    current_user: dict = Depends(require_admin),
) -> ProfileResponse:
    """Update member status (active / suspended / pending). Logs to admin_audit_log."""
    updated = await admin_service.update_status(
        admin_id=current_user["sub"],
        member_id=member_id,
        new_status=body.status,
        reason=body.reason,
    )
    return ProfileResponse(**updated)


# ── PATCH /admin/members/{member_id}/enrollment-no ───────────────────────────

@router.patch("/members/{member_id}/enrollment-no", response_model=ProfileResponse)
async def update_member_enrollment_no(
    member_id: str,
    body: EnrollmentUpdateRequest,
    current_user: dict = Depends(require_admin),
) -> ProfileResponse:
    """Update a member's enrollment / SCN number. Validates format, enforces uniqueness,
    and logs the change to admin_audit_log."""
    updated = await admin_service.update_enrollment_no(
        admin_id=current_user["sub"],
        member_id=member_id,
        new_enrollment_no=body.enrollment_no,
    )
    return ProfileResponse(**updated)


# ── GET /admin/members/{member_id}/vcard ─────────────────────────────────────

@router.get("/members/{member_id}/vcard", response_class=Response)
async def get_member_vcard(
    member_id: str,
    current_user: dict = Depends(require_admin),
) -> Response:
    """Return member contact info as a downloadable vCard (.vcf) file."""
    profile = await admin_service.get_member_detail(member_id)
    vcard_str = await admin_service.get_vcard(member_id)
    member_uid = profile.get("member_uid", member_id)
    return Response(
        content=vcard_str,
        media_type="text/vcard",
        headers={"Content-Disposition": f'attachment; filename="{member_uid}.vcf"'},
    )


# ── POST /admin/members/{member_id}/regenerate-qr ────────────────────────────

@router.post("/members/{member_id}/regenerate-qr")
async def regenerate_member_qr(
    member_id: str,
    current_user: dict = Depends(require_admin),
) -> dict:
    """Regenerate and re-upload the QR code for a member. Logs to admin_audit_log."""
    url = await admin_service.regenerate_qr(
        admin_id=current_user["sub"],
        member_id=member_id,
    )
    return {"qr_code_url": url}


# ── GET /admin/export ─────────────────────────────────────────────────────────

@router.get("/export", response_class=Response)
async def export_members(
    status: str | None = None,
    branch: str | None = None,
    payment_status: str | None = None,
    current_user: dict = Depends(require_admin),
) -> Response:
    """Bulk CSV export of members with optional filters."""
    csv_str = await admin_service.export_csv(
        status_filter=status,
        branch=branch,
        payment_status=payment_status,
    )
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="members.csv"'},
    )


# ── GET /admin/audit-log ──────────────────────────────────────────────────────

@router.get("/audit-log", response_model=AuditLogResponse)
async def get_audit_log(
    page: int = 1,
    page_size: int = 50,
    current_user: dict = Depends(require_admin),
) -> AuditLogResponse:
    """Paginated admin action audit log, newest first."""
    entries, total = await admin_service.get_audit_log(page=page, page_size=page_size)
    return AuditLogResponse(
        total=total,
        page=page,
        page_size=page_size,
        entries=[AuditLogEntry(**e) for e in entries],
    )
