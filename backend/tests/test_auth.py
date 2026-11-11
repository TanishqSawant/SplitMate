"""Tests for user authentication: registration, login, JWT validation, and token expiration."""

from datetime import timedelta

from app.core.security import create_access_token


def test_register_success(unauth_client):
    """Successful registration returns 201 with access token and user info (without password hash)."""
    resp = unauth_client.post(
        "/api/auth/register",
        json={
            "name": "New User",
            "email": "newuser@example.com",
            "password": "SecurePassword123!",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["name"] == "New User"
    assert data["user"]["email"] == "newuser@example.com"
    assert "password_hash" not in data["user"]
    assert "password" not in data["user"]


def test_register_duplicate_email(unauth_client):
    """Attempting to register with an existing email returns 400 Bad Request."""
    payload = {
        "name": "First User",
        "email": "duplicate@example.com",
        "password": "Password123!",
    }
    r1 = unauth_client.post("/api/auth/register", json=payload)
    assert r1.status_code == 201

    r2 = unauth_client.post("/api/auth/register", json=payload)
    assert r2.status_code == 400
    assert "already registered" in r2.json()["detail"].lower()


def test_register_invalid_email(unauth_client):
    """Invalid email format is rejected with 422 Unprocessable Entity."""
    resp = unauth_client.post(
        "/api/auth/register",
        json={
            "name": "Bad Email User",
            "email": "not-an-email",
            "password": "Password123!",
        },
    )
    assert resp.status_code == 422


def test_register_short_password(unauth_client):
    """Password shorter than 8 characters is rejected with 422."""
    resp = unauth_client.post(
        "/api/auth/register",
        json={
            "name": "Short Pwd",
            "email": "short@example.com",
            "password": "short",
        },
    )
    assert resp.status_code == 422


def test_login_success(unauth_client):
    """Valid credentials return 200 with JWT access token."""
    unauth_client.post(
        "/api/auth/register",
        json={
            "name": "Login User",
            "email": "login@example.com",
            "password": "CorrectPassword123!",
        },
    )

    resp = unauth_client.post(
        "/api/auth/login",
        json={
            "email": "login@example.com",
            "password": "CorrectPassword123!",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "login@example.com"


def test_login_incorrect_password(unauth_client):
    """Incorrect password returns 401 Unauthorized."""
    unauth_client.post(
        "/api/auth/register",
        json={
            "name": "Login User",
            "email": "login_bad_pwd@example.com",
            "password": "CorrectPassword123!",
        },
    )

    resp = unauth_client.post(
        "/api/auth/login",
        json={
            "email": "login_bad_pwd@example.com",
            "password": "WrongPassword456!",
        },
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


def test_login_nonexistent_email(unauth_client):
    """Non-existent email returns 401 Unauthorized without leaking email existence."""
    resp = unauth_client.post(
        "/api/auth/login",
        json={
            "email": "nobody@example.com",
            "password": "SomePassword123!",
        },
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


def test_me_authenticated(client):
    """Authenticated user can fetch their own profile from /api/auth/me."""
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == client.auth_user.email
    assert data["name"] == client.auth_user.name
    assert "password_hash" not in data


def test_missing_token_returns_401(unauth_client):
    """Requests to protected endpoints without a token return 401."""
    resp = unauth_client.get("/api/auth/me")
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def test_invalid_token_returns_401(unauth_client):
    """Malformed or tampered JWT returns 401."""
    resp = unauth_client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer this.is.an.invalid.token"},
    )
    assert resp.status_code == 401
    assert "Could not validate credentials" in resp.json()["detail"]


def test_expired_token_returns_401(unauth_client, default_user):
    """Expired JWT returns 401."""
    expired_token = create_access_token(
        {"sub": str(default_user.id), "email": default_user.email},
        expires_delta=timedelta(minutes=-10),
    )
    resp = unauth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


def test_password_hash_never_exposed(unauth_client):
    """Verify that password hash is not in any response."""
    reg = unauth_client.post(
        "/api/auth/register",
        json={
            "name": "Secret User",
            "email": "secret@example.com",
            "password": "Password123!",
        },
    )
    assert "password_hash" not in reg.text
    token = reg.json()["access_token"]

    login = unauth_client.post(
        "/api/auth/login",
        json={"email": "secret@example.com", "password": "Password123!"},
    )
    assert "password_hash" not in login.text

    me = unauth_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert "password_hash" not in me.text


def test_production_rejects_missing_or_insecure_jwt_secret():
    """In production environment, missing or default JWT secrets must be rejected."""
    import pytest
    from app.core.config import Settings

    # Missing / empty secret
    with pytest.raises(ValueError, match="JWT_SECRET_KEY must be explicitly configured"):
        Settings(APP_ENV="production", JWT_SECRET_KEY="")

    # Insecure default dev secret
    with pytest.raises(ValueError, match="JWT_SECRET_KEY must be explicitly configured"):
        Settings(
            APP_ENV="production",
            JWT_SECRET_KEY="dev-insecure-jwt-secret-key-not-for-production",
        )

    # Secret shorter than 32 characters
    with pytest.raises(ValueError, match="JWT_SECRET_KEY must be explicitly configured"):
        Settings(APP_ENV="production", JWT_SECRET_KEY="short-secret-1234")


def test_production_accepts_strong_jwt_secret():
    """In production environment, a strong 32+ character secret is accepted."""
    from app.core.config import Settings

    strong_secret = "a-very-strong-production-secret-key-that-is-at-least-32-chars!"
    cfg = Settings(APP_ENV="production", JWT_SECRET_KEY=strong_secret)
    assert cfg.JWT_SECRET_KEY == strong_secret


def test_development_uses_documented_insecure_key(monkeypatch):
    """In development, a clearly marked dev-only default key is used if unset."""
    from app.core.config import Settings

    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    cfg = Settings(
        APP_ENV="development",
        _env_file=None,
    )

    assert cfg.JWT_SECRET_KEY == "dev-insecure-jwt-secret-key-not-for-production"

