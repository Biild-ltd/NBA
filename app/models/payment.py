from pydantic import BaseModel


class PaymentInitResponse(BaseModel):
    """Response for POST /payments/initialise."""
    authorization_url: str
    reference: str


class PaymentVerifyResponse(BaseModel):
    """Response for GET /payments/verify/{reference} and items in history."""
    reference: str
    status: str          # "pending" | "success" | "failed"
    amount: int          # in kobo
    currency: str
    created_at: str
    verified_at: str | None = None


class PaymentHistoryResponse(BaseModel):
    """Response for GET /payments/history."""
    transactions: list[PaymentVerifyResponse]
