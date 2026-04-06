"""
Shared pytest fixtures for the NBA Backend test suite.

Environment variables are set here BEFORE any app module is imported so that
Pydantic Settings can construct the `settings` singleton without a real .env file.
"""
import os
import time

# Inject test credentials before any app import touches pydantic-settings.
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-role-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "super-secret-jwt-key-for-testing-only")
os.environ.setdefault("PAYSTACK_SECRET_KEY", "sk_test_xxxxxxxxxxxxxxxxxxxx")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-xxxxxxxxxxxxxxxxxxxx")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:3000")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.main import app

_TEST_JWT_SECRET = "super-secret-jwt-key-for-testing-only"


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Synchronous test client for the FastAPI app (session-scoped)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def make_token():
    """Factory fixture — returns a callable that generates signed test JWTs.

    Usage:
        token = make_token()                    # default member
        token = make_token(role="admin")        # admin user
        token = make_token(user_id="uuid-...")  # specific user
    """
    def _make(user_id: str = "test-user-00000000", role: str = "member") -> str:
        now = int(time.time())
        payload = {
            "sub": user_id,
            "iat": now,
            "exp": now + 3600,
            "app_metadata": {"role": role},
            "user_metadata": {},
        }
        return jwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")

    return _make


@pytest.fixture(scope="session")
def auth_headers(make_token):
    """Authorization headers for a default test member."""
    return {"Authorization": f"Bearer {make_token()}"}


@pytest.fixture(scope="session")
def admin_headers(make_token):
    """Authorization headers for a test admin."""
    return {"Authorization": f"Bearer {make_token(role='admin')}"}


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset in-memory rate-limit counters before and after every test function.

    Without this, requests from one test accumulate against the shared per-IP
    bucket and cause subsequent tests to receive unexpected 429 responses.
    """
    from app.limiter import limiter
    try:
        limiter._storage.reset()
    except Exception:
        pass
    yield
    try:
        limiter._storage.reset()
    except Exception:
        pass
