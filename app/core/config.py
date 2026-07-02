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

    # File storage (Cloudflare R2 / S3-compatible). Leave blank to use local
    # disk storage so uploads work in development without any cloud account.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_public_url: str = ""  # optional public base URL for the bucket
    local_storage_dir: str = "uploads"
    backend_public_url: str = "http://localhost:8000"
    max_upload_mb: int = 10

    # Email (Resend). Leave the API key blank to run in mock mode — emails are
    # logged to the console instead of being sent.
    resend_api_key: str = ""
    email_from: str = "noreply@agencyflow.in"
    email_from_name: str = "AgencyFlow"

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

    @property
    def storage_enabled(self) -> bool:
        return bool(
            self.r2_account_id
            and self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_bucket
        )

    @property
    def email_enabled(self) -> bool:
        return bool(self.resend_api_key)

    # WhatsApp (Meta Cloud API). Leave blank to run in mock mode.
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""

    # AI (Anthropic Claude). Leave blank to run in mock mode.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    ai_rate_limit: str = "20/minute"

    # Background jobs (Celery + Redis). Falls back to in-process async when Redis is unavailable.
    redis_url: str = "redis://localhost:6379/0"
    whatsapp_auto_on_payment: bool = True
    whatsapp_auto_on_invoice_send: bool = True
    whatsapp_template_language: str = "en"

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.whatsapp_token and self.whatsapp_phone_number_id)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def celery_enabled(self) -> bool:
        return bool(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
