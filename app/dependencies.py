import logging

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")

_jwks_cache: dict | None = None


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            _jwks_cache = resp.json()
    return _jwks_cache


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Verify Supabase JWT and return the decoded payload.

    Supports both HS256 (verified with SUPABASE_JWT_SECRET) and
    RS256/ES256 (verified via Supabase JWKS endpoint).
    Raises HTTP 401 if the token is missing, expired, or invalid.
    The returned dict includes 'sub' (user UUID) and 'app_metadata' (role).
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )

    alg = header.get("alg", "HS256")
    kid = header.get("kid")

    try:
        if alg == "HS256":
            key: str | dict = settings.SUPABASE_JWT_SECRET
            algorithms = ["HS256"]
        else:
            jwks = await _get_jwks()
            keys = jwks.get("keys", [])
            if kid:
                matching = [k for k in keys if k.get("kid") == kid]
                key = matching[0] if matching else (keys[0] if keys else {})
            else:
                key = keys[0] if keys else {}
            algorithms = [alg]

        payload = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            options={"verify_aud": False},
        )
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as exc:
        logger.warning("JWT decode failed: %s | alg=%s", exc, alg)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Extend get_current_user — additionally requires role == 'admin'.

    Role is read from app_metadata in the Supabase JWT, which is set
    server-side only via the auth trigger / Supabase Admin API.
    Raises HTTP 403 if the authenticated user is not an admin.
    """
    role = current_user.get("app_metadata", {}).get("role")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FORBIDDEN",
        )
    return current_user
