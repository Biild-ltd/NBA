from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.photo import PhotoUploadResponse, PhotoValidateResponse
from app.services import photo_service, storage_service

router = APIRouter(prefix="/photos", tags=["Photos"])


def _raise_photo_rejected(result) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "PHOTO_REJECTED",
            "message": "Your photo did not pass compliance checks.",
            "details": {"failures": result.failures, "score": result.score},
        },
    )


@router.post("/validate")
@limiter.limit("5/minute")
async def validate_photo(
    request: Request,
    photo: UploadFile = File(..., description="Photo to validate — JPEG or PNG, max 5 MB"),
    current_user: dict = Depends(get_current_user),
) -> PhotoValidateResponse:
    """Validate a passport photo without storing it.

    Runs Stage 1 (file-level) and Stage 2 (Claude Vision) checks.
    Returns a pass/fail result with individual failure reasons.
    Photo is never stored, regardless of outcome.
    Rate limited to 5 requests per minute per IP.
    """
    data = await photo.read()
    mime_type = photo_service.validate_photo_stage1(data)  # raises 422 on Stage 1 failure
    result = await photo_service.validate_photo_stage2(data, mime_type)
    if not result.passed:
        _raise_photo_rejected(result)
    return PhotoValidateResponse(
        passed=result.passed, score=result.score, failures=result.failures
    )


@router.post("/upload", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def upload_photo(
    request: Request,
    photo: UploadFile = File(..., description="Photo to validate and store — JPEG or PNG, max 5 MB"),
    current_user: dict = Depends(get_current_user),
) -> PhotoUploadResponse:
    """Validate a passport photo and store it in Supabase Storage.

    Photo is only stored if both Stage 1 and Stage 2 checks pass.
    Returns the signed URL of the stored photo along with validation details.
    Rate limited to 5 requests per minute per IP.
    """
    data = await photo.read()
    mime_type = photo_service.validate_photo_stage1(data)  # raises 422 on Stage 1 failure
    result = await photo_service.validate_photo_stage2(data, mime_type)
    if not result.passed:
        _raise_photo_rejected(result)
    photo_url = await storage_service.upload_photo(current_user["sub"], data, mime_type)
    return PhotoUploadResponse(
        photo_url=photo_url,
        passed=result.passed,
        score=result.score,
        failures=result.failures,
    )
