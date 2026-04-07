import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Verify Supabase JWT and return the decoded payload.

    Raises HTTP 401 if the token is missing, expired, or invalid.
    The returned dict includes 'sub' (user UUID) and 'app_metadata' (role).
    """
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except ExpiredSignatureError:
        logger.warning("JWT expired: alg=HS256 secret_len=%d", len(settings.SUPABASE_JWT_SECRET))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TOKEN",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as exc:
        logger.warning("JWT decode failed: %s | alg=HS256 secret_len=%d", exc, len(settings.SUPABASE_JWT_SECRET))
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
