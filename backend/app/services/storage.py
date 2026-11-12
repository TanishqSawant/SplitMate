"""Unified storage adapter supporting Cloudflare R2 (S3-compatible) and local filesystem fallback.

Ensures seamless deployment resilience:
1. When Cloudflare R2 credentials (R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID) are set,
   uploaded receipt images are durably stored in R2 object storage.
2. When credentials are not configured (local dev, offline test suites), transparently falls back
   to local disk storage in settings.UPLOAD_DIR without crashing or failing tests.
"""

import io
import logging
import os
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Manages file storage across Cloudflare R2 (S3 API) and local disk fallback."""

    def __init__(self):
        self._s3_client: Any = None

    @property
    def is_r2_configured(self) -> bool:
        """Check whether Cloudflare R2 credentials are fully populated."""
        return bool(
            settings.R2_ACCESS_KEY_ID
            and settings.R2_SECRET_ACCESS_KEY
            and settings.R2_ACCOUNT_ID
            and not settings.R2_ACCESS_KEY_ID.startswith("mock")
        )

    def _get_s3_client(self):
        """Lazy-initialize boto3 S3 client for Cloudflare R2."""
        if self._s3_client is None:
            import boto3
            from botocore.config import Config

            endpoint_url = settings.r2_endpoint_url
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                region_name="auto",
                config=Config(signature_version="s3v4"),
            )
        return self._s3_client

    def save_file(
        self,
        content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Save file bytes to R2 or local storage. Returns stored location identifier."""
        if self.is_r2_configured:
            try:
                client = self._get_s3_client()
                key = f"receipts/{filename}"
                client.put_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=key,
                    Body=content,
                    ContentType=content_type,
                )
                logger.info("Saved receipt to Cloudflare R2: bucket=%s, key=%s", settings.R2_BUCKET_NAME, key)
                return f"r2://{settings.R2_BUCKET_NAME}/{key}"
            except Exception as e:
                logger.error("Failed to upload to Cloudflare R2: %s. Falling back to local storage.", e)

        # Local storage fallback
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / filename
        with open(file_path, "wb") as f:
            f.write(content)
        return str(file_path)

    def read_file(self, stored_location: str) -> bytes:
        """Read file bytes from Cloudflare R2 or local filesystem."""
        if stored_location.startswith("r2://"):
            parts = stored_location.replace("r2://", "").split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            client = self._get_s3_client()
            resp = client.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()

        path = Path(stored_location)
        if not path.exists():
            raise FileNotFoundError(f"Receipt file not found: {stored_location}")
        return path.read_bytes()

    def file_exists(self, stored_location: str) -> bool:
        """Check whether a stored file exists."""
        if stored_location.startswith("r2://"):
            try:
                parts = stored_location.replace("r2://", "").split("/", 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ""
                client = self._get_s3_client()
                client.head_object(Bucket=bucket, Key=key)
                return True
            except Exception:
                return False

        return Path(stored_location).exists()

    def delete_file(self, stored_location: str) -> bool:
        """Delete stored file from R2 or local filesystem."""
        if stored_location.startswith("r2://"):
            try:
                parts = stored_location.replace("r2://", "").split("/", 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ""
                client = self._get_s3_client()
                client.delete_object(Bucket=bucket, Key=key)
                return True
            except Exception as e:
                logger.warning("Failed to delete from R2: %s", e)
                return False

        path = Path(stored_location)
        if path.exists():
            try:
                path.unlink()
                return True
            except Exception as e:
                logger.warning("Failed to delete local file %s: %s", path, e)
                return False
        return False


storage_service = StorageService()
