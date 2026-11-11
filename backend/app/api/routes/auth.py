"""Authentication and user session routes for SplitMate."""

import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import bearer_scheme, get_current_user
from app.core.security import REVOKED_TOKENS, create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.models import User
from app.schemas.schemas import (
    TokenResponse,
    UserLogin,
    UserProfileUpdateRequest,
    UserRegister,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Re-export for backward compatibility
_REVOKED_TOKENS = REVOKED_TOKENS


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Optional dependency: Return authenticated User if a valid Bearer token is sent, else None."""
    if not credentials or not credentials.credentials:
        return None

    token = credentials.credentials
    if token in REVOKED_TOKENS:
        return None

    try:
        from app.core.security import decode_access_token
        payload = decode_access_token(token)
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            return None
        return db.get(User, uuid.UUID(user_id_raw))
    except Exception:
        return None


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new SplitMate user",
)
def register(body: UserRegister, db: Session = Depends(get_db)):
    normalized_email = body.email.strip().lower()

    existing_user = (
        db.query(User)
        .filter(func.lower(User.email) == normalized_email)
        .first()
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered.",
        )

    user = User(
        name=body.name.strip(),
        email=normalized_email,
        password_hash=hash_password(body.password),
        paypal_email=getattr(body, "paypal_email", None),
        avatar=getattr(body, "avatar", None),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "name": user.name}
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate user and obtain a session token",
)
def login(body: UserLogin, db: Session = Depends(get_db)):
    normalized_email = body.email.strip().lower()

    user = (
        db.query(User)
        .filter(func.lower(User.email) == normalized_email)
        .first()
    )
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "name": user.name}
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get currently authenticated user profile (Protected route)",
)
def get_me(current_user: User = Depends(get_current_user)):
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
def logout(
    authorization: str | None = Header(None, alias="Authorization"),
):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        REVOKED_TOKENS.add(token)
    return {"status": "ok", "message": "Successfully logged out."}
