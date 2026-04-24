from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # ── Cloud SQL (PostgreSQL) ────────────────────────────────────────────────
    # Instance connection name: "project-id:region:instance-name"
    CLOUD_SQL_INSTANCE: str
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str

    # ── JWT ───────────────────────────────────────────────────────────────────
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    JWT_SECRET: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Google Cloud Storage ──────────────────────────────────────────────────
    GCS_BUCKET: str = "nba-member-assets"

    # ── SMTP (for password reset emails) ─────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@nba.org.ng"

    # ── Paystack ──────────────────────────────────────────────────────────────
    PAYSTACK_SECRET_KEY: str

    # ── Anthropic (Claude Vision photo validation) ────────────────────────────
    ANTHROPIC_API_KEY: str

    # ── App ───────────────────────────────────────────────────────────────────
    MEMBERSHIP_FEE_KOBO: int = 500000
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    FRONTEND_ORIGIN: str = ""
    ENVIRONMENT: str = "development"

    # ── Payment bypass (set True while Paystack merchant account is pending) ────
    BYPASS_PAYMENT: bool = False



settings = Settings()
