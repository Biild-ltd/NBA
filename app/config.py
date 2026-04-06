from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    SUPABASE_ANON_KEY: str
    SUPABASE_JWT_SECRET: str

    # Paystack
    PAYSTACK_SECRET_KEY: str

    # Anthropic
    ANTHROPIC_API_KEY: str

    # App
    MEMBERSHIP_FEE_KOBO: int = 500000
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    FRONTEND_ORIGIN: str = ""
    ENVIRONMENT: str = "development"


settings = Settings()
