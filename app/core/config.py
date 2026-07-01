from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AgencyFlow CRM"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agencyflow"

    secret_key: str = "dev-secret-change-in-production"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    cors_origins: str = "http://localhost:3000"
    rate_limit: str = "100/minute"

    frontend_url: str = "http://localhost:3000"
    currency: str = "INR"

    # Payments — when no real keys are set, payments run in mock mode so the
    # full pay → webhook → "paid" flow can be tested locally.
    payments_mock: bool = True
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # Google Sign-In (OAuth 2.0 client ID from Google Cloud Console)
    google_client_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def razorpay_enabled(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key)

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
