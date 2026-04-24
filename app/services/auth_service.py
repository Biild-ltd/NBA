"""Authentication service — custom JWT auth backed by Cloud SQL PostgreSQL.

Passwords are hashed with bcrypt (cost 12).
Access tokens are HS256 JWTs (15-minute expiry).
Refresh tokens are opaque 32-byte hex strings; only their SHA-256 hash is
stored in the database so a DB leak does not expose live tokens.
"""
import asyncio
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import jwt
from passlib.context import CryptContext

from app.config import settings
from app.db.postgres import get_pool
from app.services import email_service

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _hash_token(raw: str) -> str:
    """SHA-256 hex digest — used for refresh and reset tokens."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _create_access_token(user_id: str, email: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def _make_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). Store only the hash."""
    raw = secrets.token_hex(32)
    return raw, _hash_token(raw)


# ── Async public API ──────────────────────────────────────────────────────────

async def register(email: str, password: str) -> dict:
    email = email.lower().strip()
    pool = await get_pool()

    existing = await pool.fetchrow(
        "SELECT id FROM users WHERE email = $1", email
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # bcrypt is CPU-bound (~100 ms) — run in thread to avoid blocking the loop
    password_hash = await asyncio.to_thread(_hash_password, password)

    row = await pool.fetchrow(
        "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING id, email",
        email, password_hash,
    )
    return {
        "user_id": str(row["id"]),
        "email": row["email"],
        "message": "Registration successful. You can now log in.",
    }


async def login(email: str, password: str) -> dict:
    email = email.lower().strip()
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT id, password_hash, role FROM users WHERE email = $1", email
    )
    # Use the same error for "not found" and "wrong password" to prevent
    # email enumeration
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    valid = await asyncio.to_thread(_verify_password, password, row["password_hash"])
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = str(row["id"])
    access_token = _create_access_token(user_id, email, row["role"])

    raw_refresh, hashed_refresh = _make_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    await pool.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
        row["id"], hashed_refresh, expires_at,
    )

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "user_id": user_id,
    }


async def refresh(refresh_token: str) -> dict:
    hashed = _hash_token(refresh_token)
    pool = await get_pool()

    row = await pool.fetchrow(
        """
        SELECT rt.id, rt.expires_at, u.id AS user_id, u.email, u.role
          FROM refresh_tokens rt
          JOIN users u ON u.id = rt.user_id
         WHERE rt.token_hash = $1
        """,
        hashed,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if row["expires_at"] < datetime.now(timezone.utc):
        # Clean up the expired row
        await pool.execute("DELETE FROM refresh_tokens WHERE id = $1", row["id"])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Token rotation: delete the used token before issuing a new one
    await pool.execute("DELETE FROM refresh_tokens WHERE id = $1", row["id"])

    user_id = str(row["user_id"])
    access_token = _create_access_token(user_id, row["email"], row["role"])

    raw_refresh, hashed_refresh = _make_refresh_token()
    new_expires = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    await pool.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
        row["user_id"], hashed_refresh, new_expires,
    )

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
    }


async def logout(refresh_token: str) -> None:
    """Delete the refresh token from the DB. Silently succeeds if not found."""
    hashed = _hash_token(refresh_token)
    pool = await get_pool()
    await pool.execute(
        "DELETE FROM refresh_tokens WHERE token_hash = $1", hashed
    )


async def forgot_password(email: str) -> None:
    """Generate a one-hour reset token and email it. Always returns silently
    regardless of whether the email exists (prevents enumeration)."""
    email = email.lower().strip()
    pool = await get_pool()

    row = await pool.fetchrow("SELECT id FROM users WHERE email = $1", email)
    if not row:
        return  # don't reveal that the account doesn't exist

    raw, hashed = secrets.token_urlsafe(32), None
    hashed = _hash_token(raw)

    # Clear any previous unused reset tokens for this user
    await pool.execute(
        "DELETE FROM password_reset_tokens WHERE user_id = $1", row["id"]
    )

    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await pool.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
        row["id"], hashed, expires_at,
    )

    reset_link = f"{settings.FRONTEND_ORIGIN}/reset-password?token={raw}"
    await email_service.send_password_reset(email, reset_link)


async def reset_password(token: str, new_password: str) -> None:
    """Consume a password-reset token and update the password.

    Deletes all refresh tokens for the user afterward (forces re-login
    on all devices).
    """
    hashed = _hash_token(token)
    pool = await get_pool()

    row = await pool.fetchrow(
        """
        SELECT id, user_id, expires_at, used_at
          FROM password_reset_tokens
         WHERE token_hash = $1
        """,
        hashed,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or has already been used.",
        )
    if row["used_at"] is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or has already been used.",
        )
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or has already been used.",
        )

    new_hash = await asyncio.to_thread(_hash_password, new_password)

    # Update password, mark token as used, invalidate all sessions atomically
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET password_hash = $1 WHERE id = $2",
                new_hash, row["user_id"],
            )
            await conn.execute(
                "UPDATE password_reset_tokens SET used_at = $1 WHERE id = $2",
                datetime.now(timezone.utc), row["id"],
            )
            await conn.execute(
                "DELETE FROM refresh_tokens WHERE user_id = $1", row["user_id"]
            )


async def change_password(user_id: str, current_password: str, new_password: str) -> None:
    """Verify the current password then update to the new one.

    Invalidates all existing refresh tokens so other devices are logged out.
    An attacker with only a JWT cannot change the password — the current
    password is always required.
    """
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT password_hash FROM users WHERE id = $1", user_id
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PROFILE_NOT_FOUND")

    valid = await asyncio.to_thread(_verify_password, current_password, row["password_hash"])
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    new_hash = await asyncio.to_thread(_hash_password, new_password)

    async with (await get_pool()).acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET password_hash = $1 WHERE id = $2",
                new_hash, user_id,
            )
            await conn.execute(
                "DELETE FROM refresh_tokens WHERE user_id = $1", user_id
            )
