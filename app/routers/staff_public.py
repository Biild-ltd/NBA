from fastapi import APIRouter

from app.services import staff_service

router = APIRouter(prefix="/staff", tags=["Staff"])


@router.get("/{staff_id}")
async def get_staff_profile(staff_id: str) -> dict:
    """Public staff profile — no authentication required."""
    return await staff_service.get_public_profile(staff_id)
