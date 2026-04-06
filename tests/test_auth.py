"""Tests for /v1/auth/* endpoints.

All Supabase calls are patched at the service layer so no real network
requests are made. Tests verify HTTP status codes, response shapes, and
edge-case error handling.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── /auth/register ────────────────────────────────────────────────────────────

class TestRegister:
    def test_success_returns_201(self, client):
        payload = {
            "user_id": "uuid-001",
            "email": "lawyer@nba.org.ng",
            "message": "Registration successful. Please check your email to confirm your account.",
        }
        with patch(
            "app.routers.auth.auth_service.register", new_callable=AsyncMock
        ) as mock_reg:
            mock_reg.return_value = payload
            resp = client.post(
                "/v1/auth/register",
                json={"email": "lawyer@nba.org.ng", "password": "Password1!"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] == "uuid-001"
        assert data["email"] == "lawyer@nba.org.ng"
        assert "message" in data

    def test_invalid_email_returns_422(self, client):
        resp = client.post(
            "/v1/auth/register",
            json={"email": "not-an-email", "password": "Password1!"},
        )
        assert resp.status_code == 422

    def test_short_password_returns_422(self, client):
        resp = client.post(
            "/v1/auth/register",
            json={"email": "lawyer@nba.org.ng", "password": "short"},
        )
        assert resp.status_code == 422

    def test_duplicate_email_returns_409(self, client):
        from fastapi import HTTPException
        with patch(
            "app.routers.auth.auth_service.register", new_callable=AsyncMock
        ) as mock_reg:
            mock_reg.side_effect = HTTPException(
                status_code=409, detail="An account with this email already exists."
            )
            resp = client.post(
                "/v1/auth/register",
                json={"email": "existing@nba.org.ng", "password": "Password1!"},
            )
        assert resp.status_code == 409


# ── /auth/login ───────────────────────────────────────────────────────────────

class TestLogin:
    def test_success_returns_tokens(self, client):
        payload = {
            "access_token": "eyJhbGci.test.token",
            "refresh_token": "refresh.test.token",
            "token_type": "bearer",
            "user_id": "uuid-001",
        }
        with patch(
            "app.routers.auth.auth_service.login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.return_value = payload
            resp = client.post(
                "/v1/auth/login",
                json={"email": "lawyer@nba.org.ng", "password": "Password1!"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "eyJhbGci.test.token"
        assert data["token_type"] == "bearer"
        assert "refresh_token" in data

    def test_invalid_credentials_returns_401(self, client):
        from fastapi import HTTPException
        with patch(
            "app.routers.auth.auth_service.login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.side_effect = HTTPException(
                status_code=401,
                detail="INVALID_TOKEN",
                headers={"WWW-Authenticate": "Bearer"},
            )
            resp = client.post(
                "/v1/auth/login",
                json={"email": "lawyer@nba.org.ng", "password": "wrong"},
            )
        assert resp.status_code == 401

    def test_missing_fields_returns_422(self, client):
        resp = client.post("/v1/auth/login", json={"email": "lawyer@nba.org.ng"})
        assert resp.status_code == 422


# ── /auth/logout ──────────────────────────────────────────────────────────────

class TestLogout:
    def test_success_returns_204(self, client, auth_headers):
        with patch(
            "app.routers.auth.auth_service.logout", new_callable=AsyncMock
        ) as mock_out:
            mock_out.return_value = None
            resp = client.post("/v1/auth/logout", headers=auth_headers)
        assert resp.status_code == 204

    def test_no_token_returns_401(self, client):
        resp = client.post("/v1/auth/logout")
        assert resp.status_code == 401


# ── /auth/refresh ─────────────────────────────────────────────────────────────

class TestRefresh:
    def test_success_returns_new_tokens(self, client):
        payload = {
            "access_token": "new.access.token",
            "refresh_token": "new.refresh.token",
            "token_type": "bearer",
        }
        with patch(
            "app.routers.auth.auth_service.refresh", new_callable=AsyncMock
        ) as mock_ref:
            mock_ref.return_value = payload
            resp = client.post(
                "/v1/auth/refresh",
                json={"refresh_token": "old.refresh.token"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "new.access.token"

    def test_invalid_refresh_token_returns_401(self, client):
        from fastapi import HTTPException
        with patch(
            "app.routers.auth.auth_service.refresh", new_callable=AsyncMock
        ) as mock_ref:
            mock_ref.side_effect = HTTPException(
                status_code=401,
                detail="INVALID_TOKEN",
                headers={"WWW-Authenticate": "Bearer"},
            )
            resp = client.post(
                "/v1/auth/refresh",
                json={"refresh_token": "expired.token"},
            )
        assert resp.status_code == 401


# ── /auth/forgot-password ─────────────────────────────────────────────────────

class TestForgotPassword:
    def test_always_returns_200(self, client):
        with patch(
            "app.routers.auth.auth_service.forgot_password", new_callable=AsyncMock
        ) as mock_fp:
            mock_fp.return_value = None
            resp = client.post(
                "/v1/auth/forgot-password",
                json={"email": "anyone@nba.org.ng"},
            )
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_invalid_email_returns_422(self, client):
        resp = client.post(
            "/v1/auth/forgot-password",
            json={"email": "not-an-email"},
        )
        assert resp.status_code == 422
