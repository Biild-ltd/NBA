from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.dependencies import get_current_user
from app.services import qr_service

router = APIRouter(prefix="/qr", tags=["QR Codes"])


@router.get("/{member_uid}", response_class=Response)
async def get_qr(member_uid: str) -> Response:
    """Return the QR code PNG for the given member_uid.

    No authentication required — suitable for embedding in print templates
    and QR scanner redirects. Returns 404 if the member_uid does not exist.
    """
    png_bytes = await qr_service.get_qr_bytes(member_uid)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/{member_uid}/download", response_class=Response)
async def download_qr(
    member_uid: str,
    _: dict = Depends(get_current_user),
) -> Response:
    """Return the QR code PNG as a downloadable file attachment.

    No authentication required — QR codes are public assets (they only encode
    a link to the member's public profile). The Content-Disposition header
    triggers a browser file download rather than an inline render.
    """
    png_bytes = await qr_service.get_qr_bytes(member_uid)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="qr-{member_uid}.png"'},
    )
