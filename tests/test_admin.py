"""Tests for /v1/admin/* endpoints and admin_service internals.

All Supabase calls are patched at the service layer.
Uses admin_headers fixture for authorised requests and auth_headers for 403 checks.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ── Shared test data ──────────────────────────────────────────────────────────

_MEMBER_ID = "test-user-00000000"
_MEMBER_UID = "NBA-ABC123-XYZ12345"

_PROFILE_ROW = {
    "id": _MEMBER_ID,
    "member_uid": _MEMBER_UID,
    "full_name": "Test Member",
    "branch": "Lagos",
    "year_of_call": 2019,
    "enrollment_no": "SCN/12345",
    "status": "active",
    "payment_status": "paid",
    "phone_number": "08012345678",
    "email_address": "test@nba.org.ng",
    "office_address": "123 Law Chambers, Lagos",
    "photo_url": "https://storage.example.com/photos/test.jpg",
    "qr_code_url": "https://storage.example.com/qrcodes/test.png",
    "profile_url": f"http://localhost:3000/profile/{_MEMBER_UID}",
    "payment_ref": "NBA-REF-001",
    "created_at": "2026-04-05T10:00:00+00:00",
    "updated_at": "2026-04-05T10:00:00+00:00",
}

_STATS = {
    "total_members": 10,
    "active_members": 7,
    "pending_members": 2,
    "suspended_members": 1,
    "paid_members": 7,
    "unpaid_members": 3,
    "latest_member": {"full_name": "Test Member", "created_at": "2026-04-05T10:00:00+00:00"},
    "members_by_branch": [{"branch": "Lagos", "count": 5}],
}

_AUDIT_ENTRY = {
    "id": "audit-uuid-001",
    "admin_id": "test-user-00000000",
    "action": "status_change",
    "target_id": _MEMBER_ID,
    "old_value": {"status": "pending"},
    "new_value": {"status": "active", "reason": None},
    "created_at": "2026-04-05T10:00:00+00:00",
}


# ── GET /v1/admin/stats ────────────────────────────────────────────────────────

class TestAdminStats:
    def test_returns_stats(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.get_stats",
            new_callable=AsyncMock,
            return_value=_STATS,
        ):
            resp = client.get("/v1/admin/stats", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_members"] == 10
        assert data["active_members"] == 7
        assert data["members_by_branch"][0]["branch"] == "Lagos"

    def test_no_auth_returns_401(self, client):
        resp = client.get("/v1/admin/stats")
        assert resp.status_code == 401

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.get("/v1/admin/stats", headers=auth_headers)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"


# ── GET /v1/admin/members ──────────────────────────────────────────────────────

class TestAdminMemberList:
    def test_returns_paginated_members(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.list_members",
            new_callable=AsyncMock,
            return_value=([_PROFILE_ROW], 1),
        ):
            resp = client.get("/v1/admin/members", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["page"] == 1
        assert len(data["members"]) == 1
        assert data["members"][0]["member_uid"] == _MEMBER_UID

    def test_filter_by_status(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.list_members",
            new_callable=AsyncMock,
            return_value=([_PROFILE_ROW], 1),
        ) as mock_list:
            resp = client.get(
                "/v1/admin/members?status=active&page=2&page_size=10",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        call_kwargs = mock_list.call_args.kwargs
        assert call_kwargs["status_filter"] == "active"
        assert call_kwargs["page"] == 2
        assert call_kwargs["page_size"] == 10

    def test_empty_result(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.list_members",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            resp = client.get("/v1/admin/members", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["members"] == []

    def test_no_auth_returns_401(self, client):
        resp = client.get("/v1/admin/members")
        assert resp.status_code == 401

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.get("/v1/admin/members", headers=auth_headers)
        assert resp.status_code == 403


# ── GET /v1/admin/members/{member_id} ─────────────────────────────────────────

class TestAdminMemberDetail:
    def test_returns_member_detail(self, client, admin_headers):
        detail = {**_PROFILE_ROW, "payment_history": []}
        with patch(
            "app.routers.admin.admin_service.get_member_detail",
            new_callable=AsyncMock,
            return_value=detail,
        ):
            resp = client.get(f"/v1/admin/members/{_MEMBER_ID}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["member_uid"] == _MEMBER_UID
        assert "payment_history" in resp.json()

    def test_not_found_returns_404(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.get_member_detail",
            new_callable=AsyncMock,
            side_effect=HTTPException(404, detail="PROFILE_NOT_FOUND"),
        ):
            resp = client.get(f"/v1/admin/members/nonexistent", headers=admin_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROFILE_NOT_FOUND"

    def test_no_auth_returns_401(self, client):
        resp = client.get(f"/v1/admin/members/{_MEMBER_ID}")
        assert resp.status_code == 401

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.get(f"/v1/admin/members/{_MEMBER_ID}", headers=auth_headers)
        assert resp.status_code == 403


# ── PATCH /v1/admin/members/{member_id}/status ────────────────────────────────

class TestAdminStatusUpdate:
    def test_updates_status_successfully(self, client, admin_headers):
        updated = {**_PROFILE_ROW, "status": "suspended"}
        with patch(
            "app.routers.admin.admin_service.update_status",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            resp = client.patch(
                f"/v1/admin/members/{_MEMBER_ID}/status",
                json={"status": "suspended", "reason": "Policy violation"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"

    def test_not_found_returns_404(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.update_status",
            new_callable=AsyncMock,
            side_effect=HTTPException(404, detail="PROFILE_NOT_FOUND"),
        ):
            resp = client.patch(
                f"/v1/admin/members/nonexistent/status",
                json={"status": "active"},
                headers=admin_headers,
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROFILE_NOT_FOUND"

    def test_invalid_status_returns_422(self, client, admin_headers):
        resp = client.patch(
            f"/v1/admin/members/{_MEMBER_ID}/status",
            json={"status": "banned"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    def test_no_auth_returns_401(self, client):
        resp = client.patch(
            f"/v1/admin/members/{_MEMBER_ID}/status",
            json={"status": "active"},
        )
        assert resp.status_code == 401

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.patch(
            f"/v1/admin/members/{_MEMBER_ID}/status",
            json={"status": "active"},
            headers=auth_headers,
        )
        assert resp.status_code == 403


# ── GET /v1/admin/members/{member_id}/vcard ───────────────────────────────────

class TestAdminVCard:
    _VCARD = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\n"
        "FN:Test Member\r\nORG:Nigerian Bar Association\r\n"
        "TEL;TYPE=CELL:08012345678\r\nEMAIL:test@nba.org.ng\r\n"
        f"ADR:;;123 Law Chambers, Lagos;;;;\r\n"
        f"NOTE:NBA Member - {_MEMBER_UID} | Branch: Lagos | Year of Call: 2019\r\n"
        "END:VCARD\r\n"
    )

    def test_returns_vcf_file(self, client, admin_headers):
        detail = {**_PROFILE_ROW, "payment_history": []}
        with (
            patch(
                "app.routers.admin.admin_service.get_member_detail",
                new_callable=AsyncMock,
                return_value=detail,
            ),
            patch(
                "app.routers.admin.admin_service.get_vcard",
                new_callable=AsyncMock,
                return_value=self._VCARD,
            ),
        ):
            resp = client.get(
                f"/v1/admin/members/{_MEMBER_ID}/vcard", headers=admin_headers
            )
        assert resp.status_code == 200
        assert "text/vcard" in resp.headers["content-type"]
        assert f'filename="{_MEMBER_UID}.vcf"' in resp.headers["content-disposition"]

    def test_not_found_returns_404(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.get_member_detail",
            new_callable=AsyncMock,
            side_effect=HTTPException(404, detail="PROFILE_NOT_FOUND"),
        ):
            resp = client.get(
                f"/v1/admin/members/nonexistent/vcard", headers=admin_headers
            )
        assert resp.status_code == 404

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.get(
            f"/v1/admin/members/{_MEMBER_ID}/vcard", headers=auth_headers
        )
        assert resp.status_code == 403


# ── POST /v1/admin/members/{member_id}/regenerate-qr ─────────────────────────

class TestAdminRegenerateQR:
    _QR_URL = "https://storage.example.com/qrcodes/test-user-00000000/qr.png"

    def test_returns_qr_url(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.regenerate_qr",
            new_callable=AsyncMock,
            return_value=self._QR_URL,
        ):
            resp = client.post(
                f"/v1/admin/members/{_MEMBER_ID}/regenerate-qr",
                headers=admin_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["qr_code_url"] == self._QR_URL

    def test_not_found_returns_404(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.regenerate_qr",
            new_callable=AsyncMock,
            side_effect=HTTPException(404, detail="PROFILE_NOT_FOUND"),
        ):
            resp = client.post(
                f"/v1/admin/members/nonexistent/regenerate-qr", headers=admin_headers
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROFILE_NOT_FOUND"

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.post(
            f"/v1/admin/members/{_MEMBER_ID}/regenerate-qr", headers=auth_headers
        )
        assert resp.status_code == 403


# ── GET /v1/admin/export ──────────────────────────────────────────────────────

class TestAdminExport:
    _CSV = "member_uid,full_name,branch\nNBA-ABC123-XYZ12345,Test Member,Lagos\n"

    def test_returns_csv(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.export_csv",
            new_callable=AsyncMock,
            return_value=self._CSV,
        ):
            resp = client.get("/v1/admin/export", headers=admin_headers)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert 'filename="members.csv"' in resp.headers["content-disposition"]
        assert "Test Member" in resp.text

    def test_no_auth_returns_401(self, client):
        resp = client.get("/v1/admin/export")
        assert resp.status_code == 401

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.get("/v1/admin/export", headers=auth_headers)
        assert resp.status_code == 403


# ── GET /v1/admin/audit-log ───────────────────────────────────────────────────

class TestAdminAuditLog:
    def test_returns_audit_log(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.get_audit_log",
            new_callable=AsyncMock,
            return_value=([_AUDIT_ENTRY], 1),
        ):
            resp = client.get("/v1/admin/audit-log", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["entries"]) == 1
        assert data["entries"][0]["action"] == "status_change"

    def test_no_auth_returns_401(self, client):
        resp = client.get("/v1/admin/audit-log")
        assert resp.status_code == 401

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.get("/v1/admin/audit-log", headers=auth_headers)
        assert resp.status_code == 403


# ── POST /v1/admin/members ────────────────────────────────────────────────────

class TestAdminCreateMember:
    _FORM = {
        "member_id": _MEMBER_ID,
        "full_name": "Test Member",
        "enrollment_no": "SCN/12345",
        "year_of_call": "2019",
        "branch": "Lagos",
        "phone_number": "08012345678",
        "email_address": "test@nba.org.ng",
        "office_address": "123 Law Chambers, Lagos",
    }

    def test_creates_member_successfully(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.create_member",
            new_callable=AsyncMock,
            return_value=_PROFILE_ROW,
        ):
            resp = client.post(
                "/v1/admin/members",
                data=self._FORM,
                headers=admin_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["member_uid"] == _MEMBER_UID
        assert resp.json()["status"] == "active"

    def test_duplicate_enrollment_returns_409(self, client, admin_headers):
        with patch(
            "app.routers.admin.admin_service.create_member",
            new_callable=AsyncMock,
            side_effect=HTTPException(409, detail="DUPLICATE_ENROLLMENT"),
        ):
            resp = client.post(
                "/v1/admin/members",
                data=self._FORM,
                headers=admin_headers,
            )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "DUPLICATE_ENROLLMENT"

    def test_no_auth_returns_401(self, client):
        resp = client.post("/v1/admin/members", data=self._FORM)
        assert resp.status_code == 401

    def test_member_role_returns_403(self, client, auth_headers):
        resp = client.post(
            "/v1/admin/members",
            data=self._FORM,
            headers=auth_headers,
        )
        assert resp.status_code == 403
