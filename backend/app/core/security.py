"""Security utilities: password hashing with bcrypt, PBKDF2 verification fallback, and JWT operations."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from typing import Any

try:
    import bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False
import jwt
from fastapi import HTTPException, status

from app.core.config import settings

# Global token revocation denylist (stores revoked JWT tokens)
REVOKED_TOKENS: set[str] = set()


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt (if installed) or PBKDF2-HMAC-SHA256."""
    if _HAS_BCRYPT:
        pwd_bytes = password.encode("utf-8")
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt or legacy PBKDF2 hash."""
    try:
        if hashed_password.startswith(("$2a$", "$2b$", "$2y$")):
            if _HAS_BCRYPT:
                return bcrypt.checkpw(
                    plain_password.encode("utf-8"),
                    hashed_password.encode("utf-8"),
                )
            return False
        # Fallback for PBKDF2 salt$key format
        if "$" in hashed_password:
            salt_hex, key_hex = hashed_password.split("$", 1)
            salt = bytes.fromhex(salt_hex)
            key = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, 100_000)
            return hmac.compare_digest(key.hex(), key_hex)
        return False
    except Exception:
        return False


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """Create a signed JWT access token with a 24-hour expiration time."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Raises HTTP 401 if the token has expired or signature is invalid.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def generate_token() -> str:
    """Generate a cryptographically secure random session/auth token (legacy fallback)."""
    return secrets.token_urlsafe(32)
