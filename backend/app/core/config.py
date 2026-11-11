"""Application configuration loaded from environment variables."""

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the SplitMate backend."""

    # Database
    DATABASE_URL: str = "postgresql://splitmate_user:password@localhost:5432/splitmate_db"

    # Application
    APP_ENV: str = "development"
    DEBUG: bool = False

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # File uploads
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # Internal service authentication (used by Pawan's AI extraction service)
    INTERNAL_SERVICE_SECRET: str = ""

    # JWT Authentication
    # In production, JWT_SECRET_KEY must be explicitly set to a strong secret (at least 32 characters).
    # In development, an explicitly documented dev-only insecure key is used if unset.
    JWT_SECRET_KEY: str = "dev-insecure-jwt-secret-key-not-for-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Google Gemini AI Configuration
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # PayPal Sandbox (Tanay configures these)
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_TIMEOUT_SECONDS: float = 10.0

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.APP_ENV == "production":
            if (
                not self.JWT_SECRET_KEY
                or len(self.JWT_SECRET_KEY) < 32
                or self.JWT_SECRET_KEY.startswith("dev-insecure")
            ):
                raise ValueError(
                    "JWT_SECRET_KEY must be explicitly configured with a strong, non-default secret "
                    "(at least 32 characters) in production environment."
                )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

