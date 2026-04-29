from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class AdminMemberSummary(BaseModel):
    id: str
    member_uid: str
    full_name: str
    branch: str
    year_of_call: int
    enrollment_no: str
    email_address: str
    phone_number: str
    office_address: str
    status: str
    payment_status: str
    photo_url: str | None
    qr_code_url: str | None
    profile_url: str
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: object) -> str:
        return str(v)


class MemberDirectoryResponse(BaseModel):
    total: int
    page: int
    page_size: int
    members: list[AdminMemberSummary]


class AdminStatsResponse(BaseModel):
    total_members: int
    active_members: int
    pending_members: int
    suspended_members: int
    paid_members: int
    unpaid_members: int
    latest_member: dict | None          # {"full_name": str, "created_at": str}
    members_by_branch: list[dict]       # [{"branch": str, "count": int}]


class EnrollmentUpdateRequest(BaseModel):
    enrollment_no: str = Field(min_length=2, max_length=50)


class StatusUpdateRequest(BaseModel):
    status: str
    reason: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in {"active", "suspended", "pending"}:
            raise ValueError("status must be active, suspended, or pending")
        return v


class AuditLogEntry(BaseModel):
    id: str
    admin_id: str
    action: str
    target_id: str
    old_value: dict | None
    new_value: dict | None
    created_at: datetime


class AuditLogResponse(BaseModel):
    total: int
    page: int
    page_size: int
    entries: list[AuditLogEntry]
