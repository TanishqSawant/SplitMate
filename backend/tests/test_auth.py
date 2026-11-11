"""Tests for User Authentication, Registration, Login, and Session Protection."""

import pytest
from app.models.models import User


def test_user_registration_success(client):
    """Test successful user registration returns HTTP 201 and access token."""
    payload = {
        "name": "Dhruv Patil",
        "email": "dhruv.test@splitmate.io",
        "password": "securepassword123",
        "paypal_email": "dhruv-sandbox@paypal.com",
    }
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "dhruv.test@splitmate.io"
    assert data["user"]["name"] == "Dhruv Patil"
    assert data["user"]["paypal_email"] == "dhruv-sandbox@paypal.com"
    assert "hashed_password" not in data["user"]


def test_user_registration_duplicate_email_rejected(client):
    """Test registering with an existing email returns HTTP 400."""
    payload = {
        "name": "Tanishq Duplicate",
        "email": "tanishq.dup@splitmate.io",
        "password": "password123",
    }
    resp1 = client.post("/api/auth/register", json=payload)
    assert resp1.status_code == 201

    resp2 = client.post("/api/auth/register", json=payload)
    assert resp2.status_code == 400
    assert "already registered" in resp2.json()["detail"].lower()


def test_user_registration_validation_errors(client):
    """Test invalid registration payload returns 422."""
    # Invalid email
    resp = client.post("/api/auth/register", json={
        "name": "Invalid",
        "email": "not-an-email",
        "password": "password123",
    })
    assert resp.status_code == 422

    # Password too short (< 6 chars)
    resp = client.post("/api/auth/register", json={
        "name": "Short Pass",
        "email": "short@splitmate.io",
        "password": "123",
    })
    assert resp.status_code == 422


def test_user_login_success(client):
    """Test successful login with correct credentials returns token and user."""
    reg_payload = {
        "name": "Pawan AI",
        "email": "pawan.login@splitmate.io",
        "password": "pawanpassword123",
    }
    client.post("/api/auth/register", json=reg_payload)

    login_resp = client.post("/api/auth/login", json={
        "email": "pawan.login@splitmate.io",
        "password": "pawanpassword123",
    })
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "pawan.login@splitmate.io"


def test_user_login_invalid_password(client):
    """Test login with wrong password returns HTTP 401."""
    reg_payload = {
        "name": "Tanay Payments",
        "email": "tanay.login@splitmate.io",
        "password": "tanaypassword123",
    }
    client.post("/api/auth/register", json=reg_payload)

    login_resp = client.post("/api/auth/login", json={
        "email": "tanay.login@splitmate.io",
        "password": "wrongpassword!",
    })
    assert login_resp.status_code == 401
    assert "invalid" in login_resp.json()["detail"].lower()


def test_user_login_nonexistent_email(client):
    """Test login with non-existent email returns HTTP 401."""
    resp = client.post("/api/auth/login", json={
        "email": "ghost@splitmate.io",
        "password": "somepassword",
    })
    assert resp.status_code == 401


def test_protected_route_me_requires_token(client):
    """Test accessing /api/auth/me without token returns HTTP 401."""
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_protected_route_me_with_valid_token(client):
    """Test accessing /api/auth/me with valid Bearer token returns profile."""
    reg_resp = client.post("/api/auth/register", json={
        "name": "Sunil Lead",
        "email": "sunil.me@splitmate.io",
        "password": "sunilpassword123",
    })
    token = reg_resp.json()["access_token"]

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Sunil Lead"
    assert resp.json()["email"] == "sunil.me@splitmate.io"


def test_protected_route_me_with_invalid_token(client):
    """Test accessing /api/auth/me with invalid Bearer token returns HTTP 401."""
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer fake_token_value_12345"})
    assert resp.status_code == 401


def test_update_profile(client):
    """Test updating user profile."""
    reg_resp = client.post("/api/auth/register", json={
        "name": "Original Name",
        "email": "update.test@splitmate.io",
        "password": "password123",
    })
    token = reg_resp.json()["access_token"]

    update_resp = client.put(
        "/api/auth/profile",
        json={"name": "Updated Name", "paypal_email": "updated@paypal.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Name"
    assert update_resp.json()["paypal_email"] == "updated@paypal.com"


def test_logout_revokes_session(client):
    """Test logout terminates session and invalidates access token."""
    reg_resp = client.post("/api/auth/register", json={
        "name": "Logout User",
        "email": "logout.test@splitmate.io",
        "password": "password123",
    })
    token = reg_resp.json()["access_token"]

    # Verify token works
    resp1 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp1.status_code == 200

    # Logout
    logout_resp = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_resp.status_code == 200

    # Verify token no longer works
    resp2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 401


def test_password_storage_security(client, db_session):
    """Verify passwords are never stored in plaintext and use PBKDF2 salt$hash."""
    plain = "mysecretplaintext123"
    client.post("/api/auth/register", json={
        "name": "Crypto Check",
        "email": "crypto@splitmate.io",
        "password": plain,
    })

    user = db_session.query(User).filter(User.email == "crypto@splitmate.io").first()
    assert user is not None
    assert plain not in user.hashed_password
    assert "$" in user.hashed_password
    salt_hex, key_hex = user.hashed_password.split("$", 1)
    assert len(salt_hex) == 32  # 16 bytes = 32 hex chars
    assert len(key_hex) == 64   # SHA-256 = 32 bytes = 64 hex chars


def test_jwt_expired_token_rejected_with_401(client, db_session):
    """Test that a signed JWT with an expiration timestamp in the past is rejected."""
    from datetime import timedelta
    from app.core.security import create_access_token

    reg_resp = client.post("/api/auth/register", json={
        "name": "Expiry User",
        "email": "expiry.test@splitmate.io",
        "password": "password123",
    })
    user_id = reg_resp.json()["user"]["id"]

    # Generate an expired token (-1 hour)
    expired_token = create_access_token(
        data={"sub": user_id, "email": "expiry.test@splitmate.io"},
        expires_delta=timedelta(hours=-1),
    )

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


def test_jwt_tampered_token_rejected_with_401(client, db_session):
    """Test that a JWT with a forged or altered payload is rejected."""
    reg_resp = client.post("/api/auth/register", json={
        "name": "Tamper User",
        "email": "tamper.test@splitmate.io",
        "password": "password123",
    })
    valid_token = reg_resp.json()["access_token"]

    # Tamper with the token string
    tampered_token = valid_token[:-4] + "wxyz"

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered_token}"})
    assert resp.status_code == 401
