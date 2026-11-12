"""Application configuration loaded from environment variables."""

from pathlib import Path
from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings

# Locate backend/.env reliably regardless of working directory and load into os.environ
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
if _ENV_FILE.is_file():
    load_dotenv(dotenv_path=_ENV_FILE)
else:
    load_dotenv()


class Settings(BaseSettings):
    """Central configuration for the SplitMate backend."""

    # Database
    DATABASE_URL: str = "postgresql://splitmate_user:password@localhost:5432/splitmate_db"

    # Application
    APP_ENV: str = "development"
    DEBUG: bool = False

    # CORS
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://localhost:3000,"
        "http://127.0.0.1:5173,http://127.0.0.1:3000,"
        "http://localhost:4173,http://127.0.0.1:4173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )
    # Production Vercel preview & production origin regex
    CORS_ORIGIN_REGEX: str = r"^https?:\/\/(?:.*\.vercel\.app|localhost:\d+|127\.0\.0\.1:\d+)$"

    # File uploads
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # Cloudflare R2 / S3-compatible Object Storage
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "splitmate-receipts"
    R2_PUBLIC_DOMAIN: str = ""

    @property
    def r2_endpoint_url(self) -> str:
        if self.R2_ACCOUNT_ID:
            return f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        return ""

    # Internal service authentication (used by Pawan's AI extraction service)
    INTERNAL_SERVICE_SECRET: str = ""

    # JWT Authentication
    # In production, JWT_SECRET_KEY must be explicitly set to a strong secret (at least 32 characters).
    # In development, an explicitly documented dev-only insecure key is used if unset.
    JWT_SECRET_KEY: str = "dev-insecure-jwt-secret-key-not-for-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Google Gemini AI Configuration
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    # PayPal Sandbox (Tanay configures these)
    PAYPAL_MODE: str = "sandbox"
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_MOCK_MODE: bool = False
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

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    model_config = {
        "env_file": str(_ENV_FILE) if _ENV_FILE.is_file() else ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
