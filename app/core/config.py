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

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
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

    # Email — provider: auto | smtp | sendgrid | resend | blank (mock).
    email_provider: str = "auto"
    resend_api_key: str = ""
    sendgrid_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = "noreply@agencyflow.in"
    email_from_name: str = "AgencyFlow"

    # SMS OTP (signup / login). Provider: twilio | msg91 | blank = mock (dev OTP on screen).
    sms_provider: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    msg91_auth_key: str = ""
    msg91_sender_id: str = ""
    msg91_otp_template_id: str = ""

    @property
    def sms_enabled(self) -> bool:
        provider = (self.sms_provider or "").strip().lower()
        if provider == "twilio":
            return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)
        if provider == "msg91":
            return bool(self.msg91_auth_key)
        return False

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
    def sendgrid_enabled(self) -> bool:
        return bool(self.sendgrid_api_key)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    @property
    def resend_enabled(self) -> bool:
        return bool(self.resend_api_key)

    @property
    def email_enabled(self) -> bool:
        return self.email_provider_name != "mock"

    @property
    def email_provider_name(self) -> str:
        provider = (self.email_provider or "auto").strip().lower()
        if provider == "smtp":
            return "smtp" if self.smtp_enabled else "mock"
        if provider == "sendgrid":
            return "sendgrid" if self.sendgrid_enabled else "mock"
        if provider == "resend":
            return "resend" if self.resend_enabled else "mock"
        # auto — best option that can reach any inbox
        if self.sendgrid_enabled:
            return "sendgrid"
        if self.smtp_enabled:
            return "smtp"
        if self.resend_enabled:
            return "resend"
        return "mock"

    def email_config_hint(self) -> str | None:
        """Human-readable hint when email is not fully configured."""
        provider = (self.email_provider or "auto").strip().lower()
        if self.email_provider_name != "mock":
            return None
        if provider == "smtp" or (provider == "auto" and self.smtp_host):
            return "Set SMTP_PASSWORD in .env (Gmail → App Password) to send to any email."
        if provider == "sendgrid" or provider == "auto":
            return (
                "Add SENDGRID_API_KEY in .env (free at sendgrid.com) and verify sender email — "
                "then you can email anyone."
            )
        return "Configure SMTP, SendGrid, or verified Resend domain in .env."

    # WhatsApp (Meta Cloud API). Leave blank to run in mock mode.
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_webhook_verify_token: str = "agencyflow-dev"

    # AI — keys stay on backend only (never frontend).
    # Provider: openai (default) | gemini | anthropic | auto | mock
    ai_llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    ai_rate_limit: str = "20/minute"
    # Optional: Google Gemini (https://aistudio.google.com/apikey)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Background jobs (Celery + Redis). Leave empty to disable Redis (e.g. PythonAnywhere).
    # Falls back to in-process async when Redis is unavailable.
    redis_url: str = "redis://localhost:6379/0"
    whatsapp_auto_on_payment: bool = True
    whatsapp_auto_on_invoice_send: bool = True
    whatsapp_template_language: str = "en"
    # Meta template for signup OTP. Default uses Meta sandbox sample (order number = OTP).
    whatsapp_otp_template: str = "jaspers_market_order_confirmation_v1"
    whatsapp_otp_template_language: str = "en_US"

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.whatsapp_token and self.whatsapp_phone_number_id)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key or self.gemini_api_key or self.anthropic_api_key)

    @property
    def ai_provider(self) -> str:
        """Which live provider to use. Default OpenAI (like One World 3D); else auto-detect."""
        preferred = (self.ai_llm_provider or "openai").strip().lower()
        if preferred == "mock":
            return "mock"
        if preferred == "openai" and self.openai_api_key:
            return "openai"
        if preferred == "gemini" and self.gemini_api_key:
            return "gemini"
        if preferred == "anthropic" and self.anthropic_api_key:
            return "anthropic"
        # auto / fallback if preferred key missing
        if self.openai_api_key:
            return "openai"
        if self.gemini_api_key:
            return "gemini"
        if self.anthropic_api_key:
            return "anthropic"
        return "mock"

    @property
    def celery_enabled(self) -> bool:
        url = (self.redis_url or "").strip().lower()
        return bool(url) and url not in ("", "none", "disabled", "false", "0")

    @property
    def redis_enabled(self) -> bool:
        return self.celery_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
