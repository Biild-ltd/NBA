"""CRUD operations for NBA staff records."""
import logging

from fastapi import HTTPException

from app.db.postgres import get_pool
from app.services.storage_service import upload_staff_photo, upload_staff_signature

logger = logging.getLogger(__name__)


async def list_staff() -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id::text, full_name, department, photo_url, signature_url, created_at "
        "FROM staff ORDER BY full_name ASC"
    )
    return [dict(r) for r in rows]


async def get_staff_member(staff_id: str) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id::text, full_name, department, photo_url, signature_url, created_at "
        "FROM staff WHERE id = $1",
        staff_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "STAFF_NOT_FOUND", "message": "Staff member not found.", "details": {}})
    return dict(row)


async def create_staff(full_name: str, department: str) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        "INSERT INTO staff (full_name, department) VALUES ($1, $2) "
        "RETURNING id::text, full_name, department, photo_url, signature_url, created_at",
        full_name.strip(),
        department.strip(),
    )
    return dict(row)


async def set_staff_photo(staff_id: str, data: bytes, content_type: str) -> dict:
    await get_staff_member(staff_id)  # 404 if not found
    url = await upload_staff_photo(staff_id, data, content_type)
    pool = await get_pool()
    row = await pool.fetchrow(
        "UPDATE staff SET photo_url = $1 WHERE id = $2 "
        "RETURNING id::text, full_name, department, photo_url, signature_url, created_at",
        url,
        staff_id,
    )
    return dict(row)


async def set_staff_signature(staff_id: str, data: bytes, content_type: str) -> dict:
    await get_staff_member(staff_id)  # 404 if not found
    url = await upload_staff_signature(staff_id, data, content_type)
    pool = await get_pool()
    row = await pool.fetchrow(
        "UPDATE staff SET signature_url = $1 WHERE id = $2 "
        "RETURNING id::text, full_name, department, photo_url, signature_url, created_at",
        url,
        staff_id,
    )
    return dict(row)


async def delete_staff(staff_id: str) -> None:
    await get_staff_member(staff_id)  # 404 if not found
    pool = await get_pool()
    await pool.execute("DELETE FROM staff WHERE id = $1", staff_id)
