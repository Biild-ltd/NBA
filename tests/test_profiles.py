"""Tests for /v1/profiles/* endpoints.

Supabase DB and Storage calls are patched at the service layer.
Photo file validation (python-magic, Pillow) is also patched so tests
run without needing actual image files or libmagic installed.
"""
import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Shared fixtures ───────────────────────────────────────────────────────────

_PROFILE_ROW = {
    "id": "test-user-00000000",
    "full_name": "Chukwuemeka Obi",
    "enrollment_no": "SCN/12345",
    "year_of_call": 2019,
    "branch": "Lagos Branch",
    "phone_number": "08012345678",
    "email_address": "c.obi@chambers.ng",
    "office_address": "12 Marina Street, Victoria Island, Lagos",
    "photo_url": "https://supabase.co/storage/v1/object/sign/photos/test/abc.jpg",
    "qr_code_url": None,
    "member_uid": "NBA-ABC123-XYZ12345",
    "profile_url": "http://localhost:3000/profile/NBA-ABC123-XYZ12345",
    "status": "active",
    "payment_ref": None,
    "payment_status": "unpaid",
    "created_at": "2026-04-05T12:00:00+00:00",
    "updated_at": "2026-04-05T12:00:00+00:00",
}

_MULTIPART_FIELDS = {
    "full_name": "Chukwuemeka Obi",
    "enrollment_no": "SCN/12345",
    "year_of_call": "2019",
    "branch": "Lagos Branch",
    "phone_number": "08012345678",
    "email_address": "c.obi@chambers.ng",
    "office_address": "12 Marina Street, Victoria Island, Lagos",
}

# Minimal valid JPEG header bytes (enough for tests — real validation is mocked)
_FAKE_JPEG = b"\xff\xd8\xff" + b"\x00" * 100


# ── GET /v1/profiles/me ───────────────────────────────────────────────────────

class TestGetMyProfile:
    def test_success_returns_profile(self, client, auth_headers):
        with patch(
            "app.routers.profiles.profile_service.get_my_profile",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = _PROFILE_ROW
            resp = client.get("/v1/profiles/me", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["member_uid"] == "NBA-ABC123-XYZ12345"
        assert data["full_name"] == "Chukwuemeka Obi"

    def test_no_token_returns_401(self, client):
        resp = client.get("/v1/profiles/me")
        assert resp.status_code == 401

    def test_profile_not_found_returns_404(self, client, auth_headers):
        from fastapi import HTTPException
        with patch(
            "app.routers.profiles.profile_service.get_my_profile",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.side_effect = HTTPException(404, detail="PROFILE_NOT_FOUND")
            resp = client.get("/v1/profiles/me", headers=auth_headers)
        assert resp.status_code == 404


# ── POST /v1/profiles ─────────────────────────────────────────────────────────

class TestCreateProfile:
    def _post(self, client, headers, fields=None, photo=None):
        fields = fields or _MULTIPART_FIELDS
        photo_bytes = photo or _FAKE_JPEG
        return client.post(
            "/v1/profiles",
            data=fields,
            files={"photo": ("photo.jpg", io.BytesIO(photo_bytes), "image/jpeg")},
            headers=headers,
        )

    def test_success_returns_201(self, client, auth_headers):
        with patch(
            "app.routers.profiles.profile_service.create_profile",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = _PROFILE_ROW
            resp = self._post(client, auth_headers)

        assert resp.status_code == 201
        data = resp.json()
        assert data["member_uid"] == "NBA-ABC123-XYZ12345"
        assert data["enrollment_no"] == "SCN/12345"

    def test_no_token_returns_401(self, client):
        resp = self._post(client, headers={})
        assert resp.status_code == 401

    def test_invalid_branch_returns_422(self, client, auth_headers):
        bad_fields = {**_MULTIPART_FIELDS, "branch": "NotABranch"}
        with patch(
            "app.routers.profiles.profile_service.create_profile",
            new_callable=AsyncMock,
        ):
            resp = self._post(client, auth_headers, fields=bad_fields)
        assert resp.status_code == 422

    def test_invalid_phone_returns_422(self, client, auth_headers):
        bad_fields = {**_MULTIPART_FIELDS, "phone_number": "1234567890"}
        with patch(
            "app.routers.profiles.profile_service.create_profile",
            new_callable=AsyncMock,
        ):
            resp = self._post(client, auth_headers, fields=bad_fields)
        assert resp.status_code == 422

    def test_future_year_of_call_returns_422(self, client, auth_headers):
        bad_fields = {**_MULTIPART_FIELDS, "year_of_call": "2099"}
        with patch(
            "app.routers.profiles.profile_service.create_profile",
            new_callable=AsyncMock,
        ):
            resp = self._post(client, auth_headers, fields=bad_fields)
        assert resp.status_code == 422

    def test_duplicate_enrollment_returns_409(self, client, auth_headers):
        from fastapi import HTTPException
        with patch(
            "app.routers.profiles.profile_service.create_profile",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.side_effect = HTTPException(409, detail="DUPLICATE_ENROLLMENT")
            resp = self._post(client, auth_headers)
        assert resp.status_code == 409


# ── PUT /v1/profiles/me ───────────────────────────────────────────────────────

class TestUpdateMyProfile:
    def test_success_updates_phone(self, client, auth_headers):
        updated_row = {**_PROFILE_ROW, "phone_number": "09012345678"}
        with patch(
            "app.routers.profiles.profile_service.update_my_profile",
            new_callable=AsyncMock,
        ) as mock_upd:
            mock_upd.return_value = updated_row
            resp = client.put(
                "/v1/profiles/me",
                data={"phone_number": "09012345678"},
                headers=auth_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["phone_number"] == "09012345678"

    def test_no_token_returns_401(self, client):
        resp = client.put("/v1/profiles/me", data={"phone_number": "09012345678"})
        assert resp.status_code == 401

    def test_invalid_phone_returns_422(self, client, auth_headers):
        with patch(
            "app.routers.profiles.profile_service.update_my_profile",
            new_callable=AsyncMock,
        ):
            resp = client.put(
                "/v1/profiles/me",
                data={"phone_number": "0001"},
                headers=auth_headers,
            )
        assert resp.status_code == 422


# ── GET /v1/profiles/{member_uid} (public) ────────────────────────────────────

class TestGetPublicProfile:
    def test_active_profile_is_returned(self, client):
        with patch(
            "app.routers.profiles.profile_service.get_public_profile",
            new_callable=AsyncMock,
        ) as mock_pub:
            mock_pub.return_value = _PROFILE_ROW
            resp = client.get("/v1/profiles/NBA-ABC123-XYZ12345")
        assert resp.status_code == 200
        assert resp.json()["member_uid"] == "NBA-ABC123-XYZ12345"

    def test_nonexistent_uid_returns_404(self, client):
        from fastapi import HTTPException
        with patch(
            "app.routers.profiles.profile_service.get_public_profile",
            new_callable=AsyncMock,
        ) as mock_pub:
            mock_pub.side_effect = HTTPException(404, detail="PROFILE_NOT_FOUND")
            resp = client.get("/v1/profiles/NBA-NOTEXIST-00000000")
        assert resp.status_code == 404

    def test_no_auth_required(self, client):
        """Public endpoint must not require a token."""
        with patch(
            "app.routers.profiles.profile_service.get_public_profile",
            new_callable=AsyncMock,
        ) as mock_pub:
            mock_pub.return_value = _PROFILE_ROW
            resp = client.get("/v1/profiles/NBA-ABC123-XYZ12345")
        assert resp.status_code == 200


# ── Profile model validation unit tests ──────────────────────────────────────

class TestProfileValidation:
    def test_valid_nigerian_phones(self):
        from app.models.profile import ProfileCreate
        for phone in ["07012345678", "08012345678", "08112345678",
                       "09012345678", "09112345678"]:
            p = ProfileCreate(
                full_name="Test User",
                enrollment_no="SCN/001",
                year_of_call=2010,
                branch="Lagos Branch",
                phone_number=phone,
                email_address="test@test.com",
                office_address="1 Test Street, Lagos Island, Lagos",
            )
            assert p.phone_number == phone

    def test_invalid_phone_raises(self):
        from pydantic import ValidationError
        from app.models.profile import ProfileCreate
        with pytest.raises(ValidationError):
            ProfileCreate(
                full_name="Test User",
                enrollment_no="SCN/001",
                year_of_call=2010,
                branch="Lagos Branch",
                phone_number="0501234567",  # invalid prefix
                email_address="test@test.com",
                office_address="1 Test Street, Lagos Island, Lagos",
            )

    def test_enrollment_no_uppercased(self):
        from app.models.profile import ProfileCreate
        p = ProfileCreate(
            full_name="Test User",
            enrollment_no="scn/001",
            year_of_call=2010,
            branch="Lagos Branch",
            phone_number="08012345678",
            email_address="test@test.com",
            office_address="1 Test Street, Lagos Island, Lagos",
        )
        assert p.enrollment_no == "SCN/001"

    def test_invalid_branch_raises(self):
        from pydantic import ValidationError
        from app.models.profile import ProfileCreate
        with pytest.raises(ValidationError):
            ProfileCreate(
                full_name="Test User",
                enrollment_no="SCN/001",
                year_of_call=2010,
                branch="Atlantis",
                phone_number="08012345678",
                email_address="test@test.com",
                office_address="1 Test Street, Lagos Island, Lagos",
            )
