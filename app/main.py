import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.db.postgres import close_pool, open_pool
from app.limiter import limiter
from app.routers import admin, auth, payments, photos, profiles, qr, utility

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting NBA Backend API | environment=%s", settings.ENVIRONMENT)
    await open_pool()
    yield
    await close_pool()
    logger.info("Shutting down NBA Backend API")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="NBA ID Card Portal API",
    description="Backend service for the Nigerian Bar Association ID Card Portal — "
    "membership registration, photo validation, payments, and digital ID issuance.",
    version="1.0.0",
    lifespan=lifespan,
    # Disable docs in production
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None if settings.ENVIRONMENT == "production" else "/redoc",
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.state.limiter = limiter


# ── CORS ──────────────────────────────────────────────────────────────────────
_allowed_origins = (
    list(filter(None, [settings.PUBLIC_BASE_URL, settings.FRONTEND_ORIGIN]))
    if settings.ENVIRONMENT == "production"
    else [
        "http://localhost:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:3000",
        "https://nba.alphacards.dev",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Content-size guard ────────────────────────────────────────────────────────
_MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB


@app.middleware("http")
async def content_size_limit_middleware(request: Request, call_next):
    """Reject requests whose declared Content-Length exceeds 10 MB."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": f"Request body must not exceed {_MAX_BODY_BYTES // (1024 * 1024)} MB.",
                    "details": {},
                }
            },
        )
    return await call_next(request)


# ── Security headers ──────────────────────────────────────────────────────────
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add OWASP-recommended security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# ── Request logging (Cloud Logging compatible) ────────────────────────────────
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log every request as structured JSON; attach X-Request-ID to the response."""
    request_id = uuid.uuid4().hex[:8]
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        '{"request_id": "%s", "method": "%s", "path": "%s", "status": %d, "duration_ms": %d}',
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(utility.router, prefix="/v1")
app.include_router(auth.router, prefix="/v1")
app.include_router(profiles.router, prefix="/v1")
app.include_router(photos.router, prefix="/v1")
app.include_router(payments.router, prefix="/v1")
app.include_router(qr.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")


# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a JSON-envelope 429 consistent with the rest of the API."""
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Too many requests. Please wait before trying again.",
                "details": {},
            }
        },
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Catch Pydantic ValidationErrors raised manually inside route handlers
    (e.g. when constructing a model from Form fields) and return 422."""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "One or more input fields are invalid.",
                "details": {"errors": exc.errors()},
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Wrap FastAPI HTTPException in the standard error envelope."""
    detail = exc.detail
    if isinstance(detail, str):
        code = detail
        message = _ERROR_MESSAGES.get(detail, detail)
        details: dict = {}
    elif isinstance(detail, dict):
        code = detail.get("code", "HTTP_ERROR")
        message = detail.get("message", str(detail))
        details = detail.get("details", {})
    else:
        code = "HTTP_ERROR"
        message = str(detail)
        details = {}

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "details": {},
            }
        },
    )


# Human-readable messages for error codes (see PRD §14.3)
_ERROR_MESSAGES: dict[str, str] = {
    "INVALID_TOKEN": "Authentication token is missing, expired, or invalid.",
    "FORBIDDEN": "You do not have permission to perform this action.",
    "PROFILE_NOT_FOUND": "No profile found for the given member UID.",
    "DUPLICATE_ENROLLMENT": "This enrollment number is already registered.",
    "PHOTO_REJECTED": "Your photo did not pass compliance checks.",
    "PAYMENT_UNVERIFIED": "This action requires a completed membership fee payment.",
    "PAYMENT_ALREADY_COMPLETED": "Membership fee payment has already been completed.",
    "PAYMENT_NOT_FOUND": "No payment transaction found for the given reference.",
    "PAYMENT_GATEWAY_ERROR": "Payment gateway is temporarily unavailable.",
    "WEBHOOK_INVALID": "Webhook signature verification failed.",
    "VALIDATION_ERROR": "One or more input fields are invalid.",
    "RATE_LIMIT_EXCEEDED": "Too many requests. Please wait before trying again.",
    "PAYLOAD_TOO_LARGE": "Request body exceeds the allowed size limit.",
    "INTERNAL_ERROR": "An unexpected error occurred.",
}
