"""Tests for /v1/payments/* endpoints and payment_service internals.

All Supabase and Paystack API calls are patched at the service layer.
HMAC unit tests compute signatures with the test secret from conftest.py.
"""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.payment import PaymentInitResponse, PaymentVerifyResponse

# ── Shared test data ──────────────────────────────────────────────────────────

_TEST_PAYSTACK_KEY = "sk_test_xxxxxxxxxxxxxxxxxxxx"  # matches conftest PAYSTACK_SECRET_KEY

_INIT_RESULT = {
    "authorization_url": "https://checkout.paystack.com/test-auth",
    "reference": "NBA-ABCD1234EFGH5678",
}

_TX_PENDING = {
    "id": "uuid-tx-001",
    "reference": "NBA-ABCD1234EFGH5678",
    "status": "pending",
    "amount": 500000,
    "currency": "NGN",
    "created_at": "2026-04-05T10:00:00+00:00",
    "verified_at": None,
    "member_id": "test-user-00000000",
    "paystack_data": None,
}

_TX_SUCCESS = {**_TX_PENDING, "status": "success", "verified_at": "2026-04-05T10:05:00+00:00"}


def _charge_success_body(reference: str = "NBA-ABCD1234EFGH5678") -> bytes:
    return json.dumps(
        {
            "event": "charge.success",
            "data": {
                "reference": reference,
                "status": "success",
                "amount": 500000,
            },
        }
    ).encode()


def _make_signature(body: bytes, key: str = _TEST_PAYSTACK_KEY) -> str:
    return hmac.new(key.encode("utf-8"), body, hashlib.sha512).hexdigest()


# ── POST /v1/payments/initialise ──────────────────────────────────────────────

class TestInitialisePayment:
    def test_returns_auth_url(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.initialise_payment",
            new_callable=AsyncMock,
            return_value=_INIT_RESULT,
        ):
            resp = client.post("/v1/payments/initialise", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["authorization_url"] == _INIT_RESULT["authorization_url"]
        assert data["reference"] == _INIT_RESULT["reference"]

    def test_no_token_returns_401(self, client):
        resp = client.post("/v1/payments/initialise")
        assert resp.status_code == 401

    def test_profile_not_found_returns_404(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.initialise_payment",
            new_callable=AsyncMock,
            side_effect=HTTPException(404, detail="PROFILE_NOT_FOUND"),
        ):
            resp = client.post("/v1/payments/initialise", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PROFILE_NOT_FOUND"

    def test_already_paid_returns_409(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.initialise_payment",
            new_callable=AsyncMock,
            side_effect=HTTPException(409, detail="PAYMENT_ALREADY_COMPLETED"),
        ):
            resp = client.post("/v1/payments/initialise", headers=auth_headers)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PAYMENT_ALREADY_COMPLETED"

    def test_paystack_error_returns_502(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.initialise_payment",
            new_callable=AsyncMock,
            side_effect=HTTPException(502, detail="PAYMENT_GATEWAY_ERROR"),
        ):
            resp = client.post("/v1/payments/initialise", headers=auth_headers)
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "PAYMENT_GATEWAY_ERROR"


# ── GET /v1/payments/verify/{reference} ───────────────────────────────────────

class TestVerifyPayment:
    def test_returns_payment_status(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.verify_payment",
            new_callable=AsyncMock,
            return_value=_TX_PENDING,
        ):
            resp = client.get(
                f"/v1/payments/verify/{_TX_PENDING['reference']}",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reference"] == _TX_PENDING["reference"]
        assert data["status"] == "pending"
        assert data["amount"] == 500000
        assert data["currency"] == "NGN"
        assert data["verified_at"] is None

    def test_no_token_returns_401(self, client):
        resp = client.get("/v1/payments/verify/NBA-ABCD1234")
        assert resp.status_code == 401

    def test_not_found_returns_404(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.verify_payment",
            new_callable=AsyncMock,
            side_effect=HTTPException(404, detail="PAYMENT_NOT_FOUND"),
        ):
            resp = client.get("/v1/payments/verify/nonexistent", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PAYMENT_NOT_FOUND"


# ── POST /v1/payments/webhook ─────────────────────────────────────────────────

class TestWebhookEndpoint:
    def test_valid_webhook_returns_200(self, client):
        body = _charge_success_body()
        with patch(
            "app.routers.payments.payment_service.handle_webhook",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                "/v1/payments/webhook",
                content=body,
                headers={"x-paystack-signature": _make_signature(body)},
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_invalid_signature_returns_401(self, client):
        body = _charge_success_body()
        with patch(
            "app.routers.payments.payment_service.handle_webhook",
            new_callable=AsyncMock,
            side_effect=HTTPException(
                401,
                detail={
                    "code": "WEBHOOK_INVALID",
                    "message": "Webhook signature verification failed.",
                    "details": {},
                },
            ),
        ):
            resp = client.post(
                "/v1/payments/webhook",
                content=body,
                headers={"x-paystack-signature": "badsignature"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "WEBHOOK_INVALID"

    def test_duplicate_webhook_acknowledged(self, client):
        """Already-processed reference is acknowledged silently (200, no re-processing)."""
        body = _charge_success_body()
        with patch(
            "app.routers.payments.payment_service.handle_webhook",
            new_callable=AsyncMock,
            return_value=None,  # service returns None after idempotency early-exit
        ):
            resp = client.post(
                "/v1/payments/webhook",
                content=body,
                headers={"x-paystack-signature": _make_signature(body)},
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_non_charge_event_acknowledged(self, client):
        """Non charge.success events are ignored and return 200."""
        body = json.dumps({"event": "transfer.success", "data": {}}).encode()
        with patch(
            "app.routers.payments.payment_service.handle_webhook",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                "/v1/payments/webhook",
                content=body,
                headers={"x-paystack-signature": _make_signature(body)},
            )
        assert resp.status_code == 200


# ── GET /v1/payments/history ──────────────────────────────────────────────────

class TestPaymentHistory:
    def test_returns_transactions(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.get_payment_history",
            new_callable=AsyncMock,
            return_value=[_TX_SUCCESS],
        ):
            resp = client.get("/v1/payments/history", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["transactions"]) == 1
        assert data["transactions"][0]["status"] == "success"
        assert data["transactions"][0]["reference"] == _TX_SUCCESS["reference"]

    def test_returns_empty_list_when_no_transactions(self, client, auth_headers):
        with patch(
            "app.routers.payments.payment_service.get_payment_history",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/v1/payments/history", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["transactions"] == []

    def test_no_token_returns_401(self, client):
        resp = client.get("/v1/payments/history")
        assert resp.status_code == 401


# ── Payment service unit tests ────────────────────────────────────────────────

class TestPaymentServiceUnit:
    def test_hmac_valid(self):
        from app.services.payment_service import _verify_signature

        body = b'{"event":"charge.success"}'
        sig = hmac.new(
            _TEST_PAYSTACK_KEY.encode("utf-8"), body, hashlib.sha512
        ).hexdigest()
        assert _verify_signature(body, sig) is True

    def test_hmac_invalid_signature(self):
        from app.services.payment_service import _verify_signature

        body = b'{"event":"charge.success"}'
        assert _verify_signature(body, "deadbeefcafe") is False

    def test_hmac_wrong_key(self):
        from app.services.payment_service import _verify_signature

        body = b'{"event":"charge.success"}'
        sig = hmac.new(b"wrong-key", body, hashlib.sha512).hexdigest()
        assert _verify_signature(body, sig) is False

    async def test_initialise_calls_paystack_and_inserts(self):
        from app.services.payment_service import initialise_payment

        mock_profile = {
            "id": "test-user-00000000",
            "email_address": "test@nba.org.ng",
            "payment_status": "unpaid",
        }
        mock_paystack_resp = MagicMock()
        mock_paystack_resp.raise_for_status = MagicMock()
        mock_paystack_resp.json.return_value = {
            "data": {"authorization_url": "https://checkout.paystack.com/xyz", "reference": "NBA-TEST"}
        }

        with (
            patch(
                "app.services.payment_service._get_profile",
                return_value=mock_profile,
            ),
            patch(
                "app.services.payment_service._insert_transaction"
            ) as mock_insert,
            patch("httpx.AsyncClient") as mock_http_cls,
        ):
            mock_http = AsyncMock()
            mock_http_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(return_value=mock_paystack_resp)

            result = await initialise_payment("test-user-00000000")

        assert "authorization_url" in result
        assert "reference" in result
        mock_insert.assert_called_once()
        call_record = mock_insert.call_args[0][0]
        assert call_record["member_id"] == "test-user-00000000"
        assert call_record["status"] == "pending"

    async def test_webhook_idempotency_skips_processing(self):
        from app.services.payment_service import handle_webhook

        body = _charge_success_body(reference="NBA-ALREADY-DONE")
        sig = _make_signature(body)

        with (
            patch(
                "app.services.payment_service._get_tx_by_reference",
                return_value={"status": "success", "member_id": "test-user-00000000"},
            ),
            patch(
                "app.services.payment_service._update_transaction"
            ) as mock_update,
            patch(
                "app.services.payment_service._update_profile_payment"
            ) as mock_profile_update,
        ):
            await handle_webhook(body, sig)

        mock_update.assert_not_called()
        mock_profile_update.assert_not_called()

    async def test_webhook_non_charge_event_returns_none(self):
        from app.services.payment_service import handle_webhook

        body = json.dumps({"event": "transfer.success", "data": {}}).encode()
        sig = _make_signature(body)

        with (
            patch(
                "app.services.payment_service._get_tx_by_reference",
            ) as mock_get,
            patch(
                "app.services.payment_service._update_transaction"
            ) as mock_update,
        ):
            result = await handle_webhook(body, sig)

        assert result is None
        mock_get.assert_not_called()
        mock_update.assert_not_called()
