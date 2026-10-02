from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "EVE Diagnostic Booking Service"
    app_version: str = "1.0.0"
    environment: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/eve_diagnostics"
    db_echo: bool = False

    # Redis / cache
    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 60

    # Auth
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    bcrypt_rounds: int = 12

    # Payments / webhooks
    webhook_secret: str = "change-me-webhook-secret"
    payment_success_rate: float = Field(default=0.9, ge=0.0, le=1.0)
    allow_payment_simulation_override: bool = True
    webhook_auto_dispatch: bool = True
    webhook_dispatch_delay_seconds: float = 0.5
    webhook_max_retries: int = 3

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_storage_url: str | None = None
    auth_rate_limit: str = "10/minute"
    payment_rate_limit: str = "30/minute"

    # Optional bootstrap admin (created on startup when both are set)
    admin_email: str | None = None
    admin_password: str | None = None


settings = Settings()
