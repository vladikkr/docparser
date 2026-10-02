from typing import Any, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "DocParser.ru"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DATABASE_URL: Any  # Supports both PostgreSQL and SQLite
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50
    CELERY_ENABLED: bool = False

    SECRET_KEY: str = "insecure-development-key-do-not-use-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    API_KEY_PREFIX: str = "dp_"
    API_KEY_LENGTH: int = 32

    RATE_LIMIT_FREE: int = 10
    RATE_LIMIT_STARTER: int = 100
    RATE_LIMIT_PRO: int = 500
    RATE_LIMIT_BUSINESS: int = 2000

    OCR_LANG: str = "rus+eng"
    OCR_USE_GPU: bool = False
    OCR_DET_DB_THRESH: float = 0.3
    OCR_DET_DB_BOX_THRESH: float = 0.6
    MAX_FILE_SIZE_MB: int = 20
    ALLOWED_MIME_TYPES: list[str] = [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
    ]

    FNS_API_BASE_URL: str = "https://proverkacheka.nalog.ru:9999/v1"
    FNS_API_TIMEOUT: int = 30
    FNS_MAX_RETRIES: int = 3

    # Optional credentials: default to empty so a missing value never blocks boot.
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_API_VERSION: str = "2024-06-20"

    STRIPE_PRICE_FREE: str = "price_free"
    STRIPE_PRICE_STARTER: str = "price_starter"
    STRIPE_PRICE_PRO: str = "price_pro"
    STRIPE_PRICE_BUSINESS: str = "price_business"

    EMAIL_FROM: str = "noreply@docparser.ru"
    EMAIL_API_KEY: str | None = None
    EMAIL_PROVIDER: Literal["resend", "sendgrid", "console"] = "console"

    WEBHOOK_TIMEOUT: int = 10
    WEBHOOK_MAX_RETRIES: int = 3
    WEBHOOK_RETRY_DELAYS: list[int] = [60, 300, 900]
    # Signs the webhooks we send to customers. It must be its own secret: the
    # Stripe webhook secret has a different job, and handing that one to
    # customers so they could verify our callbacks would leak it.
    WEBHOOK_SIGNING_SECRET: str = ""

    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1

    CORS_ORIGINS: list[str] = ["http://localhost:3000", "https://docparser.ru"]

    STORAGE_BUCKET: str = "documents"
    STORAGE_PUBLIC_URL: str | None = None
    # Where uploaded documents are written. Local disk suits a single instance;
    # a mounted volume keeps the files across restarts.
    UPLOAD_DIR: str = "./storage"

    # Telegram bot. The bot runs on our own machine over long polling, so it
    # needs no public HTTPS endpoint and no paid hosting.
    TELEGRAM_BOT_TOKEN: str = ""
    # Telegram numeric user id of the owner. Only this account sees the
    # approve/deny buttons and the payment requests.
    TELEGRAM_ADMIN_ID: int = 0
    # Free documents before the bot asks the owner for a paid access.
    TELEGRAM_TRIAL_LIMIT: int = 3
    TELEGRAM_STATE_FILE: str = "./storage/bot_users.json"
    TELEGRAM_MAX_FILE_MB: int = 20

    @property
    def stripe_configured(self) -> bool:
        return bool(self.STRIPE_SECRET_KEY)

    @property
    def redis_configured(self) -> bool:
        return bool(self.REDIS_URL) and "localhost" not in self.REDIS_URL

    @property
    def telegram_configured(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN)

    @property
    def webhooks_configured(self) -> bool:
        """Whether outgoing webhooks can be signed at all.

        With no signing secret every callback would carry a signature made from
        an empty key, which looks valid and protects nothing.
        """
        return bool(self.WEBHOOK_SIGNING_SECRET)

    @property
    def telegram_admin_configured(self) -> bool:
        return self.TELEGRAM_ADMIN_ID > 0


settings = Settings()
