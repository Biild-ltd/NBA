"""Authentication service — thin wrapper around Supabase Auth.

All Supabase SDK calls are synchronous; they are wrapped with
asyncio.to_thread() so route handlers can stay async.
"""
import asyncio
import logging

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.db.supabase import get_anon_client

logger = logging.getLogger(__name__)


# ── Sync helpers (run inside thread pool) ────────────────────────────────────

def _sign_up(email: str, password: str):
    return get_anon_client().auth.sign_up({"email": email, "password": password})


def _sign_in(email: str, password: str):
    return get_anon_client().auth.sign_in_with_password(
        {"email": email, "password": password}
    )


def _refresh(refresh_token: str):
    return get_anon_client().auth.refresh_session(refresh_token)


def _reset_password(email: str) -> None:
    get_anon_client().auth.reset_password_for_email(email)


# ── Async public API ──────────────────────────────────────────────────────────

async def register(email: str, password: str) -> dict:
    try:
        result = await asyncio.to_thread(_sign_up, email, password)
    except Exception as exc:
        msg = str(exc).lower()
        if "already registered" in msg or "user already" in msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )
        logger.warning("Supabase sign_up error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        "user_id": str(result.user.id),
        "email": result.user.email,
        "message": (
            "Registration successful. "
            "Please check your email to confirm your account."
        ),
    }


async def login(email: str, password: str) -> dict:
    try:
        result = await asyncio.to_thread(_sign_in, email, password)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session = result.session
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": "bearer",
        "user_id": str(result.user.id),
    }


async def logout(access_token: str) -> None:
    """Invalidate the session on Supabase's side via the Auth REST API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            await http.post(
                f"{settings.SUPABASE_URL}/auth/v1/logout",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "apikey": settings.SUPABASE_ANON_KEY,
                },
            )
    except Exception as exc:
        logger.warning("Supabase logout call failed (ignoring): %s", exc)


async def refresh(refresh_token: str) -> dict:
    try:
        result = await asyncio.to_thread(_refresh, refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session = result.session
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "token_type": "bearer",
    }


async def forgot_password(email: str) -> None:
    """Trigger a Supabase password-reset email. Always returns success to
    prevent email enumeration — errors are swallowed and logged only."""
    try:
        await asyncio.to_thread(_reset_password, email)
    except Exception as exc:
        logger.warning("Supabase reset_password error (suppressed): %s", exc)
