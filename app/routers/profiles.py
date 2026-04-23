from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.dependencies import get_current_user
from app.models.profile import ProfileCreate, ProfileResponse, ProfileUpdate
from app.services import profile_service

router = APIRouter(prefix="/profiles", tags=["Profiles"])


def _raise_validation_error(exc: ValidationError) -> None:
    """Convert a Pydantic ValidationError raised inside a route handler into
    an HTTPException so the standard error envelope is returned.

    Strips the 'ctx' key from Pydantic v2 error dicts because it may contain
    non-JSON-serializable objects (e.g. the original ValueError instance).
    """
    errors = [{k: v for k, v in e.items() if k != "ctx"} for e in exc.errors()]
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "VALIDATION_ERROR",
            "message": "One or more input fields are invalid.",
            "details": {"errors": errors},
        },
    )


@router.get("/me")
async def get_my_profile(
    current_user: dict = Depends(get_current_user),
) -> ProfileResponse:
    row = await profile_service.get_my_profile(current_user["sub"])
    return ProfileResponse(**row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_profile(
    # All profile fields come as multipart/form-data alongside the photo file
    full_name: str = Form(...),
    enrollment_no: str = Form(...),
    year_of_call: int = Form(...),
    branch: str = Form(...),
    phone_number: str = Form(...),
    email_address: str = Form(...),
    office_address: str = Form(...),
    photo: UploadFile = File(..., description="Passport photo — JPEG or PNG, max 5 MB"),
    current_user: dict = Depends(get_current_user),
) -> ProfileResponse:
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
        _raise_validation_error(exc)
    row = await profile_service.create_profile(current_user["sub"], data, photo)
    return ProfileResponse(**row)


@router.put("/me")
async def update_my_profile(
    full_name: Optional[str] = Form(default=None),
    year_of_call: Optional[int] = Form(default=None),
    branch: Optional[str] = Form(default=None),
    phone_number: Optional[str] = Form(default=None),
    office_address: Optional[str] = Form(default=None),
    photo: Optional[UploadFile] = File(default=None),
    current_user: dict = Depends(get_current_user),
) -> ProfileResponse:
    try:
        data = ProfileUpdate(
            full_name=full_name,
            year_of_call=year_of_call,
            branch=branch,
            phone_number=phone_number,
            office_address=office_address,
        )
    except ValidationError as exc:
        _raise_validation_error(exc)
    # Pass photo only if an actual file was submitted (not an empty upload)
    submitted_photo = photo if (photo and photo.filename) else None
    row = await profile_service.update_my_profile(
        current_user["sub"], data, submitted_photo
    )
    return ProfileResponse(**row)


@router.get("/{member_uid}")
async def get_public_profile(member_uid: str) -> ProfileResponse:
    """Public lookup by member_uid — used by QR code scan landing pages.
    Only active profiles are returned.
    """
    row = await profile_service.get_public_profile(member_uid)
    return ProfileResponse(**row)
