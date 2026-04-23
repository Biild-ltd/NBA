from fastapi import APIRouter, Depends, Request, status

from app.dependencies import get_current_user
from app.models.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
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
    request: Request,
    _: dict = Depends(get_current_user),
) -> None:
    """Invalidate the current session on Supabase. Token extracted from header."""
    auth_header = request.headers.get("authorization", "")
    token = auth_header.split(" ")[-1] if " " in auth_header else auth_header
    await auth_service.logout(token)


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


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
) -> MessageResponse:
    """Change the authenticated user's password.

    Requires the current password for verification before updating.
    """
    await auth_service.change_password(
        user_id=current_user["sub"],
        user_email=current_user["email"],
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return MessageResponse(message="Password changed successfully.")
