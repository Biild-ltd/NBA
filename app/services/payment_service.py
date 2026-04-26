"""Payment service — Paystack transaction lifecycle management.

Flow:
  initialise_payment → creates payment_transactions row (status=pending)
  handle_webhook → verifies HMAC, idempotency check, independent Paystack verify,
                   updates payment_transactions + member_profiles on success
  verify_payment  → polls payment_transactions by reference (for client callback)
  get_payment_history → lists member's transactions

All DB operations use asyncpg directly.
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
from app.db.postgres import get_pool
from app.services import qr_service

logger = logging.getLogger(__name__)

_PAYSTACK_BASE = "https://api.paystack.co"


# ── HMAC verification ──────────────────────────────────────────────────────────

def _verify_signature(raw_body: bytes, signature: str) -> bool:
    """Verify Paystack webhook HMAC-SHA512 signature."""
    computed = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


# ── Private DB helpers (extracted for testability) ────────────────────────────

async def _get_profile(user_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email_address, payment_status, year_of_call FROM public.member_profiles WHERE id = $1",
            user_id,
        )
    return dict(row) if row else None


async def _insert_transaction(record: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO public.payment_transactions
               (member_id, reference, amount, currency, status)
               VALUES ($1, $2, $3, $4, $5)""",
            record["member_id"],
            record["reference"],
            record["amount"],
            record["currency"],
            record["status"],
        )


async def _get_tx_by_reference(reference: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM public.payment_transactions WHERE reference = $1",
            reference,
        )
    return dict(row) if row else None


async def _update_transaction(reference: str, now: datetime, payload_json: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE public.payment_transactions
               SET status = 'success', verified_at = $1, paystack_data = $2::jsonb
               WHERE reference = $3""",
            now,
            payload_json,
            reference,
        )


async def _update_profile_payment(member_id: str, reference: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE public.member_profiles
               SET payment_status = 'paid', status = 'active', payment_ref = $1
               WHERE id = $2""",
            reference,
            member_id,
        )


# ── Async public API ───────────────────────────────────────────────────────────

async def initialise_payment(user_id: str) -> dict:
    """Initialise a Paystack transaction for a member.

    Raises:
        HTTPException 404 — member profile not found.
        HTTPException 409 — payment already completed.
        HTTPException 502 — Paystack API unavailable.
    """
    profile = await _get_profile(user_id)

    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")
    if profile["payment_status"] == "paid":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="PAYMENT_ALREADY_COMPLETED")

    # Members called to bar from 2019 onwards receive free digital membership
    if profile["year_of_call"] >= 2019:
        result = await bypass_payment(user_id)
        return {"free": True, "reference": result["reference"], "authorization_url": None}

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
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="PAYMENT_GATEWAY_ERROR")

    await _insert_transaction({
        "member_id": user_id,
        "reference": reference,
        "amount": settings.MEMBERSHIP_FEE_KOBO,
        "currency": "NGN",
        "status": "pending",
    })

    return {"authorization_url": data["authorization_url"], "reference": reference}


async def verify_payment(reference: str, user_id: str) -> dict:
    """Poll payment status from our DB (for client callback polling).

    Raises:
        HTTPException 404 — transaction not found or does not belong to user.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM public.payment_transactions WHERE reference = $1 AND member_id = $2",
            reference,
            user_id,
        )

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PAYMENT_NOT_FOUND")
    return dict(row)


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
        return

    event = payload.get("event")
    if event != "charge.success":
        logger.debug("Ignoring non-charge.success webhook event: %s", event)
        return

    reference = payload["data"]["reference"]

    # 3. Idempotency — already processed?
    existing = await _get_tx_by_reference(reference)
    if existing and existing["status"] == "success":
        logger.debug("Webhook already processed for reference %s", reference)
        return

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
        return

    if verify_data.get("status") != "success":
        logger.info("Paystack verify returned non-success for %s", reference)
        return

    # 5. Update payment_transactions and member_profiles
    now = datetime.now(timezone.utc)
    await _update_transaction(reference, now, json.dumps(payload))

    member_id = existing["member_id"] if existing else None
    if not member_id:
        tx = await _get_tx_by_reference(reference)
        member_id = tx["member_id"] if tx else None

    if member_id:
        await _update_profile_payment(str(member_id), reference)
        asyncio.create_task(qr_service.generate_and_store(str(member_id)))


async def get_payment_history(user_id: str) -> list[dict]:
    """Return all payment transactions for the current member, newest first."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM public.payment_transactions WHERE member_id = $1 ORDER BY created_at DESC",
            user_id,
        )
    return [dict(r) for r in rows]


async def bypass_payment(user_id: str) -> dict:
    """Temporarily bypass Paystack — mark membership as paid at ₦0 (free period).

    Used while the Paystack merchant account is pending verification.
    The full Paystack flow (initialise_payment / handle_webhook) remains intact
    and will be re-enabled once the account is verified.

    Raises:
        HTTPException 404 — member profile not found.
        HTTPException 409 — payment already completed.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT id, payment_status FROM public.member_profiles WHERE id = $1",
            user_id,
        )

    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")
    if profile["payment_status"] == "paid":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="PAYMENT_ALREADY_COMPLETED")

    reference = f"NBA-FREE-{secrets.token_hex(8).upper()}"
    now = datetime.now(timezone.utc)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO public.payment_transactions
                   (member_id, reference, amount, currency, status, verified_at)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                user_id,
                reference,
                0,
                "NGN",
                "success",
                now,
            )
            await conn.execute(
                """UPDATE public.member_profiles
                   SET payment_status = 'paid', status = 'active', payment_ref = $1
                   WHERE id = $2""",
                reference,
                user_id,
            )

    asyncio.create_task(qr_service.generate_and_store(user_id))

    logger.info("Payment bypassed (free period) for member %s, ref %s", user_id, reference)
    return {"reference": reference, "status": "success"}
