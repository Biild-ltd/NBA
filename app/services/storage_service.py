"""Google Cloud Storage service.

Handles upload and public URL generation for passport photos and QR codes.
All GCS SDK calls are synchronous and wrapped with asyncio.to_thread().

Bucket access: objects are stored with public read access.
Ensure your GCS bucket has allUsers granted the Storage Object Viewer role,
or enable uniform bucket-level access with a public IAM policy.
"""
import asyncio
import logging
import uuid

from google.cloud import storage as gcs

from app.config import settings

logger = logging.getLogger(__name__)

_client: gcs.Client | None = None


def _get_client() -> gcs.Client:
    global _client
    if _client is None:
        _client = gcs.Client()
    return _client


def _upload_sync(path: str, data: bytes, content_type: str) -> str:
    """Upload bytes to GCS and return the public URL."""
    bucket = _get_client().bucket(settings.GCS_BUCKET)
    blob = bucket.blob(path)
    blob.upload_from_string(data, content_type=content_type)
    return f"https://storage.googleapis.com/{settings.GCS_BUCKET}/{path}"


async def upload_photo(member_id: str, data: bytes, content_type: str) -> str:
    """Upload a passport photo and return its public URL.

    Storage path: photos/{member_id}/{uuid}.(jpg|png)
    """
    extension = "jpg" if "jpeg" in content_type else "png"
    path = f"photos/{member_id}/{uuid.uuid4()}.{extension}"
    return await asyncio.to_thread(_upload_sync, path, data, content_type)


async def upload_qr(member_id: str, data: bytes) -> str:
    """Upload (or overwrite) a member's QR code PNG and return its public URL.

    Storage path: qrcodes/{member_id}/qr.png
    """
    path = f"qrcodes/{member_id}/qr.png"
    return await asyncio.to_thread(_upload_sync, path, data, "image/png")
