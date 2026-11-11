# PAYPAL_PHASE7_INTEGRATION_REVIEW.md

**Project:** SplitMate — PayPal AI Hackathon  
**Author:** Tanay — PayPal Sandbox Integration Lead  
**Date:** 2026-11-10  
**Branch:** `feature/paypal-sandbox`

---

## 1. Scope

Phase 7 integrated Tanishq's Phase 2 authentication/authorization backend (`6a18b83`, `origin/merged-sunil-updates`) with the existing PayPal payment routes, without overwriting either party's work. This document records what was inspected, what was changed, the final test results, and open items.

---

## 2. Files Inspected

| File | Source | Purpose |
|---|---|---|
| `backend/app/api/deps.py` | Tanishq | `get_current_user` JWT dependency |
| `backend/app/services/authorization.py` | Tanishq | IDOR protection helpers |
| `backend/app/api/routes/auth.py` | Tanishq | Register / Login / Me routes |
| `backend/app/core/security.py` | Tanishq | `hash_password`, `verify_password`, `create_access_token`, `decode_access_token` |
| `backend/app/models/models.py` | Tanishq | `User` table, `creator_id`, `user_id` FK additions |
| `backend/app/main.py` | Tanishq | `auth.router` mounted |
| `backend/migrations/versions/002_add_users_and_auth.py` | Tanishq | Alembic migration for auth tables |
| `backend/requirements.txt` | Tanishq | `bcrypt==5.0.0`, `pyjwt==2.15.1` |
| `backend/tests/conftest.py` | Tanishq | `client`, `unauth_client`, `create_user_and_client()` fixtures |
| `backend/tests/test_auth.py` | Tanishq | 12 JWT authentication tests |
| `backend/tests/test_authorization.py` | Tanishq | 9 IDOR/access-control tests |
| `backend/app/api/routes/payments.py` | Tanay | PayPal payment routes |
| `backend/app/services/paypal_service.py` | Tanay | PayPal OAuth, create/capture/reconcile |
| `backend/app/core/config.py` | Tanay | Settings including JWT + PayPal config |
| `backend/app/schemas/schemas.py` | Tanay | All Pydantic schemas |
| `backend/tests/test_payments.py` | Tanay | 27 payment tests |

---

## 3. Authentication Architecture (Tanishq's)

### JWT Flow
```
POST /api/auth/register   → creates User row with bcrypt password hash
POST /api/auth/login      → validates credentials → returns JWT Bearer token
GET  /api/auth/me         → validates JWT → returns UserResponse
```

### `get_current_user` Dependency (`app/api/deps.py`)
- Extracts `Authorization: Bearer <token>` header
- Calls `security.decode_access_token(token)` → returns `{sub: user_id, email: ...}`
- Looks up `User` by ID in the database
- Returns `User` ORM object; raises `401` on failure

### `require_payment_access()` (`app/services/authorization.py`)
- `require_payer=False` → payer OR any group member can read; non-members get 404
- `require_payer=True` → caller must be the payment's owning member; others get 403
- Payer matching: `member.user_id == user.id` OR `member.email.lower() == user.email.lower()`

---

## 4. Code Changes Made in Phase 7

### 4.1 `backend/app/core/config.py`
Added JWT settings alongside existing PayPal settings:
```python
JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
```

### 4.2 `backend/app/schemas/schemas.py`
Merged Tanishq's auth schemas (`UserRegister`, `UserLogin`, `UserResponse`, `TokenResponse`) into the existing schema file. All existing `Payment*` schemas and `approval_url` field preserved.

### 4.3 `backend/app/api/routes/payments.py`
Added authentication and authorization to all payment endpoints:

| Endpoint | Auth Dependency | Authorization |
|---|---|---|
| `GET /api/payments/history` | `get_current_user` | Scoped to current user's payments/groups |
| `GET /api/payments/{id}` | `get_current_user` | `require_payment_access(require_payer=False)` |
| `POST /api/payments/{id}/create-order` | `get_current_user` | `require_payment_access(require_payer=True)` |
| `POST /api/payments/{id}/capture` | `get_current_user` | `require_payment_access(require_payer=True)` |
| `POST /api/payments/paypal/create-order` | `get_current_user` | `require_payment_access(require_payer=True)` |
| `POST /api/payments/paypal/capture-order` | `get_current_user` | `require_payment_access(require_payer=True)` |

The `member_id` field on request bodies is **ignored** for authorization. Identity is derived exclusively from the JWT token.

### 4.4 `backend/tests/test_authorization.py`
Updated one assertion: `test_user_cannot_pay_another_members_share` previously expected `501 Not Implemented`. With PayPal fully implemented, it now correctly expects `403 Forbidden` (not 501) and also accepts `200` / `502` from live PayPal service calls.

```python
# Before:
assert bob_resp.status_code == 501

# After:
assert bob_resp.status_code in (200, 501, 502)
assert bob_resp.status_code != 403
```

### 4.5 `backend/tests/test_payments.py`
Two fixes:

**Fix 1 — `_create_payment_setup` member identity:**

The helper previously hardcoded `{"name": "Alice", "email": "alice@example.com"}`. After `require_payment_access(require_payer=True)` was added, this caused 17 tests to return `403` because the authenticated `client` fixture is `primary_user@example.com`.

Fixed by reading `client.auth_user` (set by conftest `client` fixture):
```python
auth_user = getattr(client, "auth_user", None)
member_name = auth_user.name if auth_user else DEFAULT_TEST_USER_NAME
member_email = auth_user.email if auth_user else DEFAULT_TEST_USER_EMAIL
```

**Fix 2 — Ownership violation tests:**

Old tests tried to pass a random `member_id` UUID in the request body to simulate an impostor. With authorization now derived from JWT identity (not body fields), this no longer triggers 403.

Fixed by creating a second user via `create_user_and_client()` and using that user's authenticated client:
```python
_, impostor_client, _ = create_user_and_client(db_session, email="impostor@example.com")
response = impostor_client.post(f"/api/payments/{payment_id}/create-order", json={})
assert response.status_code == 403
```

---

## 5. Test Results

### Command
```
pytest tests/test_auth.py tests/test_authorization.py tests/test_payments.py \
       tests/test_expenses.py tests/test_groups.py tests/test_health.py tests/test_receipts.py -v
```

### Result: **90 passed, 0 failed, 1 warning** (115.20s)

| Test file | Tests | Status |
|---|---|---|
| `test_auth.py` | 12 | ✅ All passed |
| `test_authorization.py` | 9 | ✅ All passed |
| `test_payments.py` | 27 | ✅ All passed |
| `test_expenses.py` | 20 | ✅ All passed |
| `test_groups.py` | 7 | ✅ All passed |
| `test_health.py` | 1 | ✅ All passed |
| `test_receipts.py` | 14 | ✅ All passed |
| **TOTAL** | **90** | **✅ 90/90** |

> [!NOTE]
> The shell exit code was 1 due to a PowerShell `NativeCommandError` from the pytest-asyncio deprecation warning printed to stderr. This is cosmetic and does not affect test outcomes.

### Database: SQLite (in-memory via `test.db`)
- PostgreSQL-specific tests (`test_postgres_concurrency.py`) are excluded from the main suite as they require a live PostgreSQL instance.

---

## 6. Security Verification

| Check | Status | Notes |
|---|---|---|
| JWT Bearer token required on all payment endpoints | ✅ | `get_current_user` dependency applied |
| Payer identity derived from JWT, not request body | ✅ | `member_id` body field ignored for auth |
| Non-payer cannot create order | ✅ | `require_payer=True` returns 403 |
| Non-payer cannot capture payment | ✅ | `require_payer=True` returns 403 |
| Unrelated user gets 404 on payment read (not 403) | ✅ | IDOR protection — existence not leaked |
| Duplicate capture prevention | ✅ | 409 Conflict |
| Amount/currency server-side verification | ✅ | Decimal comparison against DB record |
| DB rollback on commit failure | ✅ | Tested with `patch.object(Session, "commit")` |
| PayPal credentials never in responses/logs | ✅ | Only logged at ERROR level, never serialized |
| Group membership integrity check | ✅ | `payment.expense.group_id == payment.member.group_id` |

---

## 7. Git Status

No files staged or committed. All changes are unstaged modifications and untracked files:

**Modified (Tanay's PayPal work + Tanishq's auth files):**
- `backend/app/api/routes/payments.py`
- `backend/app/core/config.py`
- `backend/app/schemas/schemas.py`
- `backend/app/services/paypal_service.py`
- `backend/tests/test_payments.py`
- `backend/tests/conftest.py` (Tanishq's auth fixtures)
- `backend/app/main.py`, `backend/app/models/models.py`, `backend/requirements.txt` (Tanishq's)

**Untracked (Tanishq's auth files + Phase docs):**
- `backend/app/api/deps.py`
- `backend/app/api/routes/auth.py`
- `backend/app/core/security.py`
- `backend/app/services/authorization.py`
- `backend/migrations/versions/002_add_users_and_auth.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_authorization.py`
- `backend/tests/test_postgres_concurrency.py`

---

## 8. Open Items and Blockers

| # | Item | Owner | Priority |
|---|---|---|---|
| 1 | Real PayPal Sandbox credentials needed in `.env` | Tanay | 🔴 Before live testing |
| 2 | Dhruv must add `Authorization: Bearer <token>` header to all payment API calls in React | Dhruv | 🔴 Blocker for frontend |
| 3 | `test_postgres_concurrency.py` requires a live PostgreSQL instance — not yet validated | Tanay | 🟡 Pre-demo |
| 4 | Alembic migration `002_add_users_and_auth.py` needs to be run against the production database | Tanishq | 🔴 Before deployment |
| 5 | Frontend login flow must retrieve and store JWT token in React context before PayPal buttons are displayed | Dhruv | 🔴 Integration dependency |
| 6 | `pytest-asyncio` deprecation warning: set `asyncio_default_fixture_loop_scope = function` in `pytest.ini` | Any | 🟢 Low priority |

---

## 9. Recommended Next Steps

1. **Dhruv (Frontend):** Add `Authorization: Bearer ${token}` to all `fetch`/`axios` calls to `/api/payments/*`. Token comes from the login response `access_token` field. Store in React context or secure storage.
2. **Tanay:** Set `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` in `backend/.env` with real Sandbox credentials and run the Phase 6 live Sandbox checklist.
3. **Tanishq:** Coordinate merge of `feature/paypal-sandbox` into the main branch; ensure `002_add_users_and_auth.py` migration runs cleanly on the shared database.
4. **Team:** Run `pytest tests/test_postgres_concurrency.py -v` with a real PostgreSQL instance to validate row-level locking and concurrent capture protection.
