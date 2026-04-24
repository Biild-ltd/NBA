from fastapi import APIRouter, Depends, status

from app.dependencies import get_current_user
from app.models.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> RegisterResponse:
    result = await auth_service.register(str(body.email), body.password)
    return RegisterResponse(**result)


@router.post("/login")
async def login(body: LoginRequest) -> LoginResponse:
    result = await auth_service.login(str(body.email), body.password)
    return LoginResponse(**result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    _: dict = Depends(get_current_user),
) -> None:
    """Delete the refresh token, invalidating the session.

    The access token remains technically valid until it expires (max 15 min)
    but cannot be renewed. The client must discard both tokens on logout.
    """
    await auth_service.logout(body.refresh_token)


@router.post("/refresh")
async def refresh_token(body: RefreshRequest) -> RefreshResponse:
    result = await auth_service.refresh(body.refresh_token)
    return RefreshResponse(**result)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest) -> MessageResponse:
    await auth_service.forgot_password(str(body.email))
    return MessageResponse(
        message="If an account with that email exists, a reset link has been sent."
    )


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest) -> MessageResponse:
    """Consume a password-reset token and set a new password.

    The token is single-use and expires after 1 hour. All existing sessions
    are invalidated after a successful reset.
    """
    await auth_service.reset_password(body.token, body.new_password)
    return MessageResponse(message="Password reset successfully. Please log in.")


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
) -> MessageResponse:
    """Change password for the authenticated user.

    Requires the current password for verification. All existing sessions
    are invalidated after a successful change.
    """
    await auth_service.change_password(
        user_id=current_user["sub"],
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return MessageResponse(message="Password changed successfully.")
