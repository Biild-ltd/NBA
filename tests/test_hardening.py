"""Phase 7 hardening tests — rate limiting, security headers, content-size guard.

Each test class is isolated by the autouse `reset_rate_limiter` fixture in
conftest.py, which clears the in-memory rate-limit counters before and after
every test function.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.models.photo import PhotoValidationResult

# Tiny fake JPEG bytes used for file upload fields.
_FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20  # JPEG magic bytes + padding
_FAKE_FILE = ("photo.jpg", _FAKE_JPEG, "image/jpeg")

# A passing Stage-2 result that photo_service mocks return.
_PASS_RESULT = PhotoValidationResult(passed=True, score=0.99, failures=[])


# ── Rate limiting ─────────────────────────────────────────────────────────────

class TestPhotoRateLimit:
    """POST /photos/validate is limited to 5 requests/minute per IP."""

    def _post_validate(self, client, auth_headers):
        return client.post(
            "/v1/photos/validate",
            files={"photo": _FAKE_FILE},
            headers=auth_headers,
        )

    def test_first_5_requests_are_not_blocked(self, client, auth_headers):
        with (
            patch("app.routers.photos.photo_service.validate_photo_stage1", return_value="image/jpeg"),
            patch(
                "app.routers.photos.photo_service.validate_photo_stage2",
                new_callable=AsyncMock,
                return_value=_PASS_RESULT,
            ),
        ):
            for _ in range(5):
                resp = self._post_validate(client, auth_headers)
                assert resp.status_code != 429, f"Unexpected 429 on request {_ + 1}"

    def test_6th_request_returns_429(self, client, auth_headers):
        with (
            patch("app.routers.photos.photo_service.validate_photo_stage1", return_value="image/jpeg"),
            patch(
                "app.routers.photos.photo_service.validate_photo_stage2",
                new_callable=AsyncMock,
                return_value=_PASS_RESULT,
            ),
        ):
            for _ in range(5):
                self._post_validate(client, auth_headers)
            resp = self._post_validate(client, auth_headers)
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


class TestPaymentRateLimit:
    """POST /payments/initialise is limited to 10 requests/minute per IP."""

    _INIT_RESULT = {
        "authorization_url": "https://paystack.com/pay/test",
        "reference": "NBA-REF-001",
        "amount": 500000,
    }

    def _post_init(self, client, auth_headers):
        return client.post("/v1/payments/initialise", headers=auth_headers)

    def test_first_10_requests_are_not_blocked(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.initialise_payment",
            new_callable=AsyncMock,
            return_value=self._INIT_RESULT,
        ):
            for i in range(10):
                resp = self._post_init(client, auth_headers)
                assert resp.status_code != 429, f"Unexpected 429 on request {i + 1}"

    def test_11th_request_returns_429(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.initialise_payment",
            new_callable=AsyncMock,
            return_value=self._INIT_RESULT,
        ):
            for _ in range(10):
                self._post_init(client, auth_headers)
            resp = self._post_init(client, auth_headers)
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    def test_unrelated_endpoint_is_never_rate_limited(self, client):
        """Unlimited endpoints (healthz) should never return 429."""
        for _ in range(20):
            resp = client.get("/v1/healthz")
            assert resp.status_code == 200


# ── Security headers ──────────────────────────────────────────────────────────

class TestSecurityHeaders:
    """Every response must carry the OWASP-recommended security headers."""

    def test_x_content_type_options(self, client):
        resp = client.get("/v1/healthz")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self, client):
        resp = client.get("/v1/healthz")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_x_xss_protection(self, client):
        resp = client.get("/v1/healthz")
        assert resp.headers.get("x-xss-protection") == "1; mode=block"

    def test_referrer_policy(self, client):
        resp = client.get("/v1/healthz")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_security_headers_present_on_401_responses(self, client):
        """Security headers must appear even on unauthenticated (401) responses."""
        resp = client.get("/v1/payments/history")  # no auth → 401, no service calls
        assert resp.status_code == 401
        assert "x-content-type-options" in resp.headers

    def test_request_id_header_present(self, client):
        resp = client.get("/v1/healthz")
        assert "x-request-id" in resp.headers
        assert len(resp.headers["x-request-id"]) == 8  # hex[:8]

    def test_no_strict_transport_security_outside_production(self, client):
        """HSTS is only added in production; test env should not have it."""
        resp = client.get("/v1/healthz")
        assert "strict-transport-security" not in resp.headers


# ── Content-size guard ────────────────────────────────────────────────────────

class TestContentSizeLimit:
    """Requests whose declared Content-Length exceeds 10 MB must be rejected."""

    def test_normal_request_passes(self, client, auth_headers):
        """A small request must not be blocked by the size guard."""
        resp = client.post(
            "/v1/photos/validate",
            files={"photo": _FAKE_FILE},
            headers=auth_headers,
        )
        # May be 401/422 for other reasons, but must NOT be 413.
        assert resp.status_code != 413

    def test_oversized_content_length_returns_413(self, client, auth_headers):
        """Content-Length > 10 MB must be rejected before the body is read."""
        oversized = 10 * 1024 * 1024 + 1  # 1 byte over 10 MB
        resp = client.post(
            "/v1/photos/validate",
            content=b"x" * oversized,
            headers={**auth_headers, "content-type": "application/octet-stream"},
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
