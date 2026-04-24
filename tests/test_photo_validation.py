"""Tests for /v1/photos/* endpoints and photo_service internals.

All Supabase and Claude Vision calls are patched at the service layer.
Stage 1 unit tests create real in-memory images via Pillow so file-level
checks (MIME, dimensions, aspect ratio) run against actual data.
"""
import hashlib
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.photo import PhotoValidationResult

# ── Shared test data ──────────────────────────────────────────────────────────

_STAGE2_PASS = PhotoValidationResult(passed=True, score=0.95, failures=[])
_STAGE2_FAIL = PhotoValidationResult(
    passed=False,
    score=0.3,
    failures=["Background is not plain white.", "Selfie detected."],
)
_SIGNED_URL = "https://supabase.co/storage/v1/object/sign/photos/test/photo.jpg"


def _jpeg_file(data: bytes | None = None):
    """Build a multipart files dict for the test client."""
    payload = data or b"\xff\xd8\xff" + b"\x00" * 100
    return {"photo": ("photo.jpg", io.BytesIO(payload), "image/jpeg")}


def _make_jpeg(width: int = 300, height: int = 400) -> bytes:
    """Create a real in-memory JPEG of the given dimensions."""
    from PIL import Image as PILImage

    img = PILImage.new("RGB", (width, height), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ── POST /v1/photos/validate ─────────────────────────────────────────────────

class TestValidatePhotoEndpoint:
    def test_valid_photo_returns_200(self, client, auth_headers):
        with (
            patch(
                "app.routers.photos.photo_service.validate_photo_stage1",
                return_value="image/jpeg",
            ),
            patch(
                "app.routers.photos.photo_service.validate_photo_stage2",
                new_callable=AsyncMock,
                return_value=_STAGE2_PASS,
            ),
        ):
            resp = client.post(
                "/v1/photos/validate", files=_jpeg_file(), headers=auth_headers
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["score"] == pytest.approx(0.95)
        assert data["failures"] == []

    def test_no_token_returns_401(self, client):
        resp = client.post("/v1/photos/validate", files=_jpeg_file())
        assert resp.status_code == 401

    def test_stage1_failure_returns_422(self, client, auth_headers):
        with patch(
            "app.routers.photos.photo_service.validate_photo_stage1",
            side_effect=HTTPException(
                422,
                detail={
                    "code": "PHOTO_REJECTED",
                    "message": "Bad MIME type.",
                    "details": {"failures": ["bad mime"], "score": 0.0},
                },
            ),
        ):
            resp = client.post(
                "/v1/photos/validate", files=_jpeg_file(), headers=auth_headers
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "PHOTO_REJECTED"
        assert body["error"]["details"]["failures"] == ["bad mime"]

    def test_stage2_failure_returns_422_with_reasons(self, client, auth_headers):
        with (
            patch(
                "app.routers.photos.photo_service.validate_photo_stage1",
                return_value="image/jpeg",
            ),
            patch(
                "app.routers.photos.photo_service.validate_photo_stage2",
                new_callable=AsyncMock,
                return_value=_STAGE2_FAIL,
            ),
        ):
            resp = client.post(
                "/v1/photos/validate", files=_jpeg_file(), headers=auth_headers
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "PHOTO_REJECTED"
        failures = body["error"]["details"]["failures"]
        assert "Background is not plain white." in failures
        assert "Selfie detected." in failures

    def test_stage2_fallback_passes(self, client, auth_headers):
        """When Stage 2 falls back (Claude unavailable), still returns passed=True."""
        fallback = PhotoValidationResult(passed=True, score=1.0, failures=[])
        with (
            patch(
                "app.routers.photos.photo_service.validate_photo_stage1",
                return_value="image/jpeg",
            ),
            patch(
                "app.routers.photos.photo_service.validate_photo_stage2",
                new_callable=AsyncMock,
                return_value=fallback,
            ),
        ):
            resp = client.post(
                "/v1/photos/validate", files=_jpeg_file(), headers=auth_headers
            )
        assert resp.status_code == 200
        assert resp.json()["passed"] is True


# ── POST /v1/photos/upload ────────────────────────────────────────────────────

class TestUploadPhotoEndpoint:
    def test_valid_photo_returns_201_with_url(self, client, auth_headers):
        with (
            patch(
                "app.routers.photos.photo_service.validate_photo_stage1",
                return_value="image/jpeg",
            ),
            patch(
                "app.routers.photos.photo_service.validate_photo_stage2",
                new_callable=AsyncMock,
                return_value=_STAGE2_PASS,
            ),
            patch(
                "app.routers.photos.storage_service.upload_photo",
                new_callable=AsyncMock,
                return_value=_SIGNED_URL,
            ),
        ):
            resp = client.post(
                "/v1/photos/upload", files=_jpeg_file(), headers=auth_headers
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["photo_url"] == _SIGNED_URL
        assert data["passed"] is True
        assert data["score"] == pytest.approx(0.95)

    def test_no_token_returns_401(self, client):
        resp = client.post("/v1/photos/upload", files=_jpeg_file())
        assert resp.status_code == 401

    def test_stage1_failure_not_stored(self, client, auth_headers):
        with (
            patch(
                "app.routers.photos.photo_service.validate_photo_stage1",
                side_effect=HTTPException(
                    422,
                    detail={
                        "code": "PHOTO_REJECTED",
                        "message": "Bad file.",
                        "details": {"failures": ["bad mime"], "score": 0.0},
                    },
                ),
            ),
            patch(
                "app.routers.photos.storage_service.upload_photo",
                new_callable=AsyncMock,
            ) as mock_upload,
        ):
            resp = client.post(
                "/v1/photos/upload", files=_jpeg_file(), headers=auth_headers
            )
        assert resp.status_code == 422
        mock_upload.assert_not_called()

    def test_stage2_rejection_not_stored(self, client, auth_headers):
        with (
            patch(
                "app.routers.photos.photo_service.validate_photo_stage1",
                return_value="image/jpeg",
            ),
            patch(
                "app.routers.photos.photo_service.validate_photo_stage2",
                new_callable=AsyncMock,
                return_value=_STAGE2_FAIL,
            ),
            patch(
                "app.routers.photos.storage_service.upload_photo",
                new_callable=AsyncMock,
            ) as mock_upload,
        ):
            resp = client.post(
                "/v1/photos/upload", files=_jpeg_file(), headers=auth_headers
            )
        assert resp.status_code == 422
        mock_upload.assert_not_called()


# ── Stage 1 unit tests ────────────────────────────────────────────────────────

class TestPhotoServiceStage1:
    """Direct unit tests for photo_service.validate_photo_stage1()."""

    def test_valid_portrait_jpeg_passes(self):
        from app.services.photo_service import validate_photo_stage1

        mime = validate_photo_stage1(_make_jpeg(300, 400))
        assert mime == "image/jpeg"

    def test_invalid_mime_raises_422(self):
        from app.services.photo_service import validate_photo_stage1

        with pytest.raises(HTTPException) as exc_info:
            validate_photo_stage1(b"this is plain text not an image")
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "PHOTO_REJECTED"
        assert any(
            "Unsupported file type" in f
            for f in exc_info.value.detail["details"]["failures"]
        )

    def test_too_large_raises_422(self):
        from app.services.photo_service import validate_photo_stage1

        # JPEG magic header + >5 MB padding so MIME passes but size fails
        large_data = b"\xff\xd8\xff" + b"\x00" * (5 * 1024 * 1024 + 100)
        with pytest.raises(HTTPException) as exc_info:
            validate_photo_stage1(large_data)
        assert exc_info.value.status_code == 422
        assert any(
            "5 MB" in f for f in exc_info.value.detail["details"]["failures"]
        )

    def test_too_small_raises_422(self):
        from app.services.photo_service import validate_photo_stage1

        data = _make_jpeg(100, 133)  # valid portrait but below 200×200 px
        with pytest.raises(HTTPException) as exc_info:
            validate_photo_stage1(data)
        assert any(
            "200×200px" in f
            for f in exc_info.value.detail["details"]["failures"]
        )

    def test_landscape_raises_422(self):
        from app.services.photo_service import validate_photo_stage1

        data = _make_jpeg(400, 250)  # landscape — 250 < 400*0.75=300, so aspect check fails
        with pytest.raises(HTTPException) as exc_info:
            validate_photo_stage1(data)
        assert any(
            "portrait" in f
            for f in exc_info.value.detail["details"]["failures"]
        )

    def test_valid_png_passes(self):
        from PIL import Image as PILImage

        from app.services.photo_service import validate_photo_stage1

        img = PILImage.new("RGB", (300, 400), color=(200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        mime = validate_photo_stage1(buf.getvalue())
        assert mime == "image/png"


# ── Stage 2 unit tests ────────────────────────────────────────────────────────

class TestPhotoServiceStage2:
    """Unit tests for photo_service.validate_photo_stage2()."""

    async def test_cache_hit_skips_claude(self):
        from app.services.photo_service import validate_photo_stage2

        cached = {"passed": True, "score": 0.9, "failures": []}
        with (
            patch("app.services.photo_service._compute_md5", return_value="abc123"),
            patch(
                "app.services.photo_service._get_cached_result",
                new_callable=AsyncMock,
                return_value=cached,
            ),
            patch("app.services.photo_service._call_claude_vision") as mock_claude,
        ):
            result = await validate_photo_stage2(b"fake", "image/jpeg")

        assert result.passed is True
        assert result.score == pytest.approx(0.9)
        mock_claude.assert_not_called()

    async def test_cache_miss_calls_claude_and_caches(self):
        from app.services.photo_service import validate_photo_stage2

        claude_result = PhotoValidationResult(passed=True, score=0.95, failures=[])
        with (
            patch("app.services.photo_service._compute_md5", return_value="abc123"),
            patch(
                "app.services.photo_service._get_cached_result",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.photo_service._call_claude_vision",
                return_value=claude_result,
            ),
            patch(
                "app.services.photo_service._save_cached_result",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            result = await validate_photo_stage2(b"fake", "image/jpeg")

        assert result.passed is True
        mock_save.assert_called_once()

    async def test_claude_api_error_returns_fallback_pass(self):
        from app.services.photo_service import validate_photo_stage2

        with (
            patch("app.services.photo_service._compute_md5", return_value="abc123"),
            patch(
                "app.services.photo_service._get_cached_result",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.photo_service._call_claude_vision",
                side_effect=Exception("Connection failed"),
            ),
        ):
            result = await validate_photo_stage2(b"fake", "image/jpeg")

        assert result.passed is True
        assert result.score == pytest.approx(1.0)
        assert result.failures == []

    async def test_stage2_fail_result_returned_and_cached(self):
        from app.services.photo_service import validate_photo_stage2

        fail_result = PhotoValidationResult(
            passed=False, score=0.3, failures=["No plain background."]
        )
        with (
            patch("app.services.photo_service._compute_md5", return_value="abc123"),
            patch(
                "app.services.photo_service._get_cached_result",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.photo_service._call_claude_vision",
                return_value=fail_result,
            ),
            patch(
                "app.services.photo_service._save_cached_result",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            result = await validate_photo_stage2(b"fake", "image/jpeg")

        assert result.passed is False
        assert "No plain background." in result.failures
        mock_save.assert_called_once()

    def test_compute_md5_is_deterministic(self):
        from app.services.photo_service import _compute_md5

        data = b"test image bytes"
        assert _compute_md5(data) == hashlib.md5(data).hexdigest()
        assert _compute_md5(data) == _compute_md5(data)
