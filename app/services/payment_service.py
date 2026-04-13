"""Payment service — Paystack transaction lifecycle management.

Flow:
  initialise_payment → creates payment_transactions row (status=pending)
  handle_webhook → verifies HMAC, idempotency check, independent Paystack verify,
                   updates payment_transactions + member_profiles on success
  verify_payment  → polls payment_transactions by reference (for client callback)
  get_payment_history → lists member's transactions
"""
import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.db.supabase import get_service_client
from app.services import qr_service

logger = logging.getLogger(__name__)

_PAYSTACK_BASE = "https://api.paystack.co"


# ── Sync DB helpers ────────────────────────────────────────────────────────────

def _get_profile(user_id: str) -> dict | None:
    result = (
        get_service_client()
        .table("member_profiles")
        .select("id, email_address, payment_status")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return result.data


def _insert_transaction(record: dict) -> dict:
    result = get_service_client().table("payment_transactions").insert(record).execute()
    return result.data[0]


def _get_tx_by_reference(reference: str) -> dict | None:
    result = (
        get_service_client()
        .table("payment_transactions")
        .select("*")
        .eq("reference", reference)
        .maybe_single()
        .execute()
    )
    return result.data


def _get_tx_by_ref_and_member(reference: str, member_id: str) -> dict | None:
    result = (
        get_service_client()
        .table("payment_transactions")
        .select("*")
        .eq("reference", reference)
        .eq("member_id", member_id)
        .maybe_single()
        .execute()
    )
    return result.data


def _update_transaction(reference: str, fields: dict) -> None:
    get_service_client().table("payment_transactions").update(fields).eq(
        "reference", reference
    ).execute()


def _update_profile_payment(member_id: str, fields: dict) -> None:
    get_service_client().table("member_profiles").update(fields).eq(
        "id", member_id
    ).execute()


def _get_history(member_id: str) -> list[dict]:
    result = (
        get_service_client()
        .table("payment_transactions")
        .select("*")
        .eq("member_id", member_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


# ── HMAC verification ──────────────────────────────────────────────────────────

def _verify_signature(raw_body: bytes, signature: str) -> bool:
    """Verify Paystack webhook HMAC-SHA512 signature."""
    computed = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


# ── Async public API ───────────────────────────────────────────────────────────

async def initialise_payment(user_id: str) -> dict:
    """Initialise a Paystack transaction for a member.

    Raises:
        HTTPException 404 — member profile not found.
        HTTPException 409 — payment already completed.
        HTTPException 502 — Paystack API unavailable.
    """
    profile = await asyncio.to_thread(_get_profile, user_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )
    if profile.get("payment_status") == "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PAYMENT_ALREADY_COMPLETED",
        )

    reference = f"NBA-{secrets.token_hex(8).upper()}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_PAYSTACK_BASE}/transaction/initialize",
                json={
                    "email": profile["email_address"],
                    "amount": settings.MEMBERSHIP_FEE_KOBO,
                    "reference": reference,
                },
                headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
    except Exception as exc:
        logger.error("Paystack initialise error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PAYMENT_GATEWAY_ERROR",
        )

    await asyncio.to_thread(
        _insert_transaction,
        {
            "member_id": user_id,
            "reference": reference,
            "amount": settings.MEMBERSHIP_FEE_KOBO,
            "currency": "NGN",
            "status": "pending",
        },
    )

    return {"authorization_url": data["authorization_url"], "reference": reference}


async def verify_payment(reference: str, user_id: str) -> dict:
    """Poll payment status from our DB (for client callback polling).

    Raises:
        HTTPException 404 — transaction not found or does not belong to user.
    """
    tx = await asyncio.to_thread(_get_tx_by_ref_and_member, reference, user_id)
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PAYMENT_NOT_FOUND",
        )
    return tx


async def handle_webhook(raw_body: bytes, signature: str) -> None:
    """Process a Paystack webhook event.

    Verifies HMAC signature, checks idempotency, independently re-verifies with
    Paystack, then updates payment_transactions and member_profiles on success.

    Raises:
        HTTPException 401 — invalid HMAC signature.
    """
    # 1. Verify signature
    if not _verify_signature(raw_body, signature):
        logger.warning("Paystack webhook signature mismatch")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "WEBHOOK_INVALID",
                "message": "Webhook signature verification failed.",
                "details": {},
            },
        )

    # 2. Parse event
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("Webhook body is not valid JSON")
        return  # Acknowledge silently

    event = payload.get("event")
    if event != "charge.success":
        logger.debug("Ignoring non-charge.success webhook event: %s", event)
        return  # Acknowledge silently

    reference = payload["data"]["reference"]

    # 3. Idempotency — already processed?
    existing = await asyncio.to_thread(_get_tx_by_reference, reference)
    if existing and existing.get("status") == "success":
        logger.debug("Webhook already processed for reference %s", reference)
        return  # Acknowledge silently

    # 4. Independent verification with Paystack API
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{_PAYSTACK_BASE}/transaction/verify/{reference}",
                headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            )
            resp.raise_for_status()
            verify_data = resp.json()["data"]
    except Exception as exc:
        logger.warning("Paystack verify call failed for %s: %s", reference, exc)
        return  # Acknowledge silently; do not mark as failed

    if verify_data.get("status") != "success":
        logger.info("Paystack verify returned non-success for %s", reference)
        return

    # 5. Update payment_transactions
    now_iso = datetime.now(timezone.utc).isoformat()
    await asyncio.to_thread(
        _update_transaction,
        reference,
        {"status": "success", "verified_at": now_iso, "paystack_data": payload},
    )

    # 6. Get member_id and activate profile
    tx = existing or await asyncio.to_thread(_get_tx_by_reference, reference)
    if tx:
        await asyncio.to_thread(
            _update_profile_payment,
            tx["member_id"],
            {"payment_status": "paid", "status": "active", "payment_ref": reference},
        )
        asyncio.create_task(qr_service.generate_and_store(tx["member_id"]))


async def get_payment_history(user_id: str) -> list[dict]:
    """Return all payment transactions for the current member, newest first."""
    return await asyncio.to_thread(_get_history, user_id)


async def bypass_payment(user_id: str) -> dict:
    """Temporarily bypass Paystack — mark membership as paid at ₦0 (free period).

    Used while the Paystack merchant account is pending verification.
    The full Paystack flow (initialise_payment / handle_webhook) remains intact
    and will be re-enabled once the account is verified.

    Raises:
        HTTPException 404 — member profile not found.
        HTTPException 409 — payment already completed.
    """
    profile = await asyncio.to_thread(_get_profile, user_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PROFILE_NOT_FOUND",
        )
    if profile.get("payment_status") == "paid":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PAYMENT_ALREADY_COMPLETED",
        )

    reference = f"NBA-FREE-{secrets.token_hex(8).upper()}"
    now_iso = datetime.now(timezone.utc).isoformat()

    await asyncio.to_thread(
        _insert_transaction,
        {
            "member_id": user_id,
            "reference": reference,
            "amount": 0,
            "currency": "NGN",
            "status": "success",
            "verified_at": now_iso,
        },
    )

    await asyncio.to_thread(
        _update_profile_payment,
        user_id,
        {"payment_status": "paid", "status": "active", "payment_ref": reference},
    )

    asyncio.create_task(qr_service.generate_and_store(user_id))

    logger.info("Payment bypassed (free period) for member %s, ref %s", user_id, reference)
    return {"reference": reference, "status": "success"}
