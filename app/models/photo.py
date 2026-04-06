from pydantic import BaseModel


class PhotoValidationResult(BaseModel):
    passed: bool
    score: float
    failures: list[str] = []


class PhotoValidateResponse(BaseModel):
    """Response for POST /photos/validate — validation result only, nothing stored."""
    passed: bool
    score: float
    failures: list[str]


class PhotoUploadResponse(BaseModel):
    """Response for POST /photos/upload — validation result + signed storage URL."""
    photo_url: str
    passed: bool
    score: float
    failures: list[str]
