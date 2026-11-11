"""Authentication and user session routes for SplitMate."""

import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, status
import jwt
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.models import User
from app.schemas.schemas import (
    AuthTokenResponse,
    UserLoginRequest,
    UserProfileUpdateRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# In-memory active session token store for backward-compatible fallback
_ACTIVE_SESSIONS: dict[str, uuid.UUID] = {}
# Token revocation denylist (stores revoked JWT tokens)
_REVOKED_TOKENS: set[str] = set()


def get_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: Extract and validate Bearer token, returning the authenticated User.

    Verifies cryptographically signed JWT tokens (24-hour expiration) and revocation status.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided or invalid Bearer format.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split("Bearer ", 1)[1].strip()

    # Reject if token was explicitly revoked via logout
    if token in _REVOKED_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked or logged out. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Primary: Verify signed JWT token
    user_id = None
    try:
        payload = decode_access_token(token)
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject claim.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = uuid.UUID(user_id_raw)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (jwt.PyJWTError, ValueError):
        # 2. Backward compatibility fallback for legacy opaque tokens
        user_id = _ACTIVE_SESSIONS.get(token)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if not user:
        _ACTIVE_SESSIONS.pop(token, None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with token not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_optional_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User | None:
    """Optional dependency: Return authenticated User if a valid Bearer token is sent, else None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.split("Bearer ", 1)[1].strip()
    if token in _REVOKED_TOKENS:
        return None

    try:
        payload = decode_access_token(token)
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            return None
        return db.get(User, uuid.UUID(user_id_raw))
    except Exception:
        legacy_id = _ACTIVE_SESSIONS.get(token)
        if legacy_id:
            return db.get(User, legacy_id)
        return None


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new SplitMate user",
)
def register_user(body: UserRegisterRequest, db: Session = Depends(get_db)):
    # Check for existing email
    existing = db.query(User).filter(User.email == body.email.lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered.",
        )

    hashed = hash_password(body.password)
    user = User(
        email=body.email.lower(),
        name=body.name.strip(),
        hashed_password=hashed,
        paypal_email=body.paypal_email,
        avatar=body.avatar,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "name": user.name}
    )
    _ACTIVE_SESSIONS[token] = user.id

    return AuthTokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=AuthTokenResponse,
    summary="Authenticate user and obtain a session token",
)
def login_user(body: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "name": user.name}
    )
    _ACTIVE_SESSIONS[token] = user.id

    return AuthTokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get currently authenticated user profile (Protected route)",
)
def get_current_user_profile(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.put(
    "/profile",
    response_model=UserResponse,
    summary="Update authenticated user profile",
)
def update_profile(
    body: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.name is not None:
        current_user.name = body.name.strip()
    if body.paypal_email is not None:
        current_user.paypal_email = body.paypal_email.strip()
    if body.avatar is not None:
        current_user.avatar = body.avatar.strip()

    db.commit()
    db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post(
    "/logout",
    summary="Terminate active session",
)
def logout_user(
    authorization: str | None = Header(None, alias="Authorization"),
):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        _ACTIVE_SESSIONS.pop(token, None)
        _REVOKED_TOKENS.add(token)
    return {"status": "ok", "message": "Successfully logged out."}
