from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import settings
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.payment import (
    PaymentBypassResponse,
    PaymentHistoryResponse,
    PaymentInitResponse,
    PaymentVerifyResponse,
    PaymentVerifyResponse as _TxItem,
)
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/initialise", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def initialise_payment(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> PaymentInitResponse:
    """Initialise a Paystack payment transaction.

    Amount is read from server-side config (MEMBERSHIP_FEE_KOBO) — never from
    the client. Returns the Paystack authorization URL and the transaction
    reference; the client should redirect the user to authorization_url.
    Rate limited to 10 requests per minute per IP.
    """
    result = await payment_service.initialise_payment(current_user["sub"])
    return PaymentInitResponse(**result)


@router.get("/verify/{reference}")
async def verify_payment(
    reference: str,
    current_user: dict = Depends(get_current_user),
) -> PaymentVerifyResponse:
    """Poll the status of a payment transaction (for the post-Paystack callback).

    Checks our database only — does not make an external Paystack call.
    Returns the transaction record owned by the authenticated user.
    """
    tx = await payment_service.verify_payment(reference, current_user["sub"])
    return PaymentVerifyResponse(
        reference=tx["reference"],
        status=tx["status"],
        amount=tx["amount"],
        currency=tx["currency"],
        created_at=str(tx["created_at"]),
        verified_at=str(tx["verified_at"]) if tx.get("verified_at") else None,
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def webhook(request: Request) -> dict:
    """Receive and process Paystack webhook events.

    Paystack-signed via HMAC-SHA512 in the x-paystack-signature header.
    Always returns HTTP 200 to Paystack (within 30 s), even for non-actionable
    events, to prevent Paystack retry storms.
    """
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")
    await payment_service.handle_webhook(raw_body, signature)
    return {"status": "ok"}


@router.post("/bypass", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def bypass_payment(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> PaymentBypassResponse:
    """Temporarily activate membership at ₦0 — Paystack account pending verification.

    Records a zero-amount transaction, marks the profile as paid/active, and
    triggers QR code generation. Disabled (returns 403) when BYPASS_PAYMENT=false.
    Rate limited to 5 requests per minute per IP.
    """
    if not settings.BYPASS_PAYMENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="BYPASS_DISABLED",
        )
    result = await payment_service.bypass_payment(current_user["sub"])
    return PaymentBypassResponse(**result)


@router.get("/history")
async def payment_history(
    current_user: dict = Depends(get_current_user),
) -> PaymentHistoryResponse:
    """List all payment transactions for the authenticated member, newest first."""
    rows = await payment_service.get_payment_history(current_user["sub"])
    transactions = [
        _TxItem(
            reference=r["reference"],
            status=r["status"],
            amount=r["amount"],
            currency=r["currency"],
            created_at=str(r["created_at"]),
            verified_at=str(r["verified_at"]) if r.get("verified_at") else None,
        )
        for r in rows
    ]
    return PaymentHistoryResponse(transactions=transactions)
