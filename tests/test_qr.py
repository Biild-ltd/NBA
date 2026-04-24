"""Tests for /v1/qr/* endpoints and qr_service internals.

All Supabase and storage calls are patched at the service layer.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

_TEST_MEMBER_UID = "NBA-ABC123-XYZ12345"
_TEST_PROFILE_URL = "http://localhost:3000/profile/NBA-ABC123-XYZ12345"
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # minimal PNG-like bytes


# ── GET /v1/qr/{member_uid} ───────────────────────────────────────────────────

class TestQREndpoints:
    def test_public_get_returns_png(self, client):
        with patch(
            "app.routers.qr.qr_service.get_qr_bytes",
            new_callable=AsyncMock,
            return_value=_FAKE_PNG,
        ):
            resp = client.get(f"/v1/qr/{_TEST_MEMBER_UID}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content == _FAKE_PNG

    def test_public_profile_not_found_returns_404(self, client):
        with patch(
            "app.routers.qr.qr_service.get_qr_bytes",
            new_callable=AsyncMock,
            side_effect=HTTPException(404, detail="PROFILE_NOT_FOUND"),
        ):
            resp = client.get(f"/v1/qr/{_TEST_MEMBER_UID}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROFILE_NOT_FOUND"

    def test_download_returns_attachment(self, client, auth_headers):
        with patch(
            "app.routers.qr.qr_service.get_qr_bytes",
            new_callable=AsyncMock,
            return_value=_FAKE_PNG,
        ):
            resp = client.get(f"/v1/qr/{_TEST_MEMBER_UID}/download", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert f'filename="qr-{_TEST_MEMBER_UID}.png"' in resp.headers["content-disposition"]
        assert resp.content == _FAKE_PNG

    def test_download_no_token_returns_png(self, client):
        with patch(
            "app.routers.qr.qr_service.get_qr_bytes",
            new_callable=AsyncMock,
            return_value=_FAKE_PNG,
        ):
            resp = client.get(f"/v1/qr/{_TEST_MEMBER_UID}/download")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    def test_download_profile_not_found_returns_404(self, client, auth_headers):
        with patch(
            "app.routers.qr.qr_service.get_qr_bytes",
            new_callable=AsyncMock,
            side_effect=HTTPException(404, detail="PROFILE_NOT_FOUND"),
        ):
            resp = client.get(f"/v1/qr/{_TEST_MEMBER_UID}/download", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROFILE_NOT_FOUND"


# ── QR service unit tests ─────────────────────────────────────────────────────

class TestQRServiceUnit:
    def test_generate_qr_png_returns_valid_png(self):
        from app.services.qr_service import _generate_qr_png

        result = _generate_qr_png(_TEST_PROFILE_URL)
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"  # PNG magic bytes

    async def test_generate_and_store_uploads_and_updates(self):
        from app.services.qr_service import generate_and_store

        mock_profile = {"id": "test-user-00000000", "member_uid": _TEST_MEMBER_UID}
        signed_url = "https://storage.example.com/qrcodes/test-user-00000000/qr.png"

        with (
            patch(
                "app.services.qr_service._get_profile_by_id",
                return_value=mock_profile,
            ),
            patch(
                "app.services.qr_service.storage_service.upload_qr",
                new_callable=AsyncMock,
                return_value=signed_url,
            ) as mock_upload,
            patch(
                "app.services.qr_service._update_qr_url"
            ) as mock_update,
        ):
            result = await generate_and_store("test-user-00000000")

        assert result == signed_url
        mock_upload.assert_called_once_with("test-user-00000000", mock_upload.call_args[0][1])
        mock_update.assert_called_once_with("test-user-00000000", signed_url)

    async def test_generate_and_store_returns_none_on_missing_profile(self):
        from app.services.qr_service import generate_and_store

        with patch(
            "app.services.qr_service._get_profile_by_id",
            return_value=None,
        ):
            result = await generate_and_store("nonexistent-id")

        assert result is None

    async def test_generate_and_store_returns_none_on_error(self):
        from app.services.qr_service import generate_and_store

        mock_profile = {"id": "test-user-00000000", "member_uid": _TEST_MEMBER_UID}

        with (
            patch(
                "app.services.qr_service._get_profile_by_id",
                return_value=mock_profile,
            ),
            patch(
                "app.services.qr_service.storage_service.upload_qr",
                new_callable=AsyncMock,
                side_effect=Exception("Storage unavailable"),
            ),
        ):
            result = await generate_and_store("test-user-00000000")

        assert result is None

    async def test_get_qr_bytes_raises_404_if_not_found(self):
        from app.services.qr_service import get_qr_bytes

        with patch(
            "app.services.qr_service._get_profile_by_uid",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_qr_bytes(_TEST_MEMBER_UID)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "PROFILE_NOT_FOUND"
