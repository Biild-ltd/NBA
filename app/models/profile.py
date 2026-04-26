import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.constants.branches import NBA_BRANCHES_SET

_PHONE_RE = re.compile(r"^(070|080|081|090|091)\d{8}$")
_ENROLLMENT_RE = re.compile(r"^[A-Za-z0-9/\-]+$")


class ProfileCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    enrollment_no: str = Field(min_length=2, max_length=50)
    year_of_call: int = Field(ge=1900)
    branch: str
    phone_number: str
    email_address: EmailStr
    office_address: str = Field(min_length=5, max_length=500)

    @field_validator("enrollment_no")
    @classmethod
    def validate_enrollment_no(cls, v: str) -> str:
        if not _ENROLLMENT_RE.match(v):
            raise ValueError(
                "Enrollment number may only contain letters, digits, '/' and '-'."
            )
        return v.upper()

    @field_validator("year_of_call")
    @classmethod
    def validate_year_of_call(cls, v: int) -> int:
        current_year = datetime.now().year
        if v > current_year:
            raise ValueError(f"Year of call cannot be in the future (max {current_year}).")
        return v

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, v: str) -> str:
        if v not in NBA_BRANCHES_SET:
            raise ValueError(f"'{v}' is not a valid NBA branch.")
        return v

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, v: str) -> str:
        if not _PHONE_RE.match(v):
            raise ValueError(
                "Phone number must be a valid Nigerian mobile number "
                "(11 digits starting with 070, 080, 081, 090, or 091)."
            )
        return v


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    year_of_call: int | None = Field(default=None, ge=1900)
    branch: str | None = None
    phone_number: str | None = None
    office_address: str | None = Field(default=None, min_length=5, max_length=500)

    @field_validator("year_of_call")
    @classmethod
    def validate_year_of_call(cls, v: int | None) -> int | None:
        if v is not None:
            current_year = datetime.now().year
            if v > current_year:
                raise ValueError(f"Year of call cannot be in the future (max {current_year}).")
        return v

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, v: str | None) -> str | None:
        if v is not None and v not in NBA_BRANCHES_SET:
            raise ValueError(f"'{v}' is not a valid NBA branch.")
        return v

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, v: str | None) -> str | None:
        if v is not None and not _PHONE_RE.match(v):
            raise ValueError(
                "Phone number must be a valid Nigerian mobile number "
                "(11 digits starting with 070, 080, 081, 090, or 091)."
            )
        return v


class ProfileResponse(BaseModel):
    id: str
    full_name: str
    enrollment_no: str
    year_of_call: int
    branch: str
    phone_number: str
    email_address: str
    office_address: str
    photo_url: str | None
    qr_code_url: str | None
    member_uid: str
    profile_url: str
    status: str
    payment_ref: str | None
    payment_status: str
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: object) -> str:
        return str(v)
