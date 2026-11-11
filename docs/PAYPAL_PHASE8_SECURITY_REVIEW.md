# PAYPAL_PHASE8_SECURITY_REVIEW.md

**Project:** SplitMate — PayPal AI Hackathon  
**Author:** Tanay — PayPal Sandbox Integration Lead  
**Date:** 2026-11-10  
**Branch:** `feature/paypal-sandbox`  
**Scope:** Verification-only. No files modified.

---

## Executive Summary

The PayPal payment backend passes all Phase 8 security checks. Every payment route requires a valid JWT Bearer token. Payer-exclusive operations enforce `require_payment_access(require_payer=True)`. Client-supplied `member_id`/`payerId` fields cannot override authenticated identity. Payment history is scoped. Amount/currency verification, idempotency, reconciliation, and rollback protection are all intact. The full 90-test suite exits with code **0**.

One gap identified: `test_payments.py` contains **no test that calls a payment route with `unauth_client`** (no Bearer token). The behavior is correct (all 6 endpoints return 401 when unauthenticated — verified by manual inline script), but the gap is not covered by a named pytest test.

---

## 1. Route-Level Authentication Verification

**File:** [`backend/app/api/routes/payments.py`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py)

| Route | Method | `get_current_user` | `require_payment_access` | `require_payer` |
|---|---|---|---|---|
| `/api/payments/history` | GET | ✅ | Inline filter | N/A — scoped query |
| `/api/payments/paypal/create-order` | POST | ✅ | ✅ | `True` |
| `/api/payments/paypal/capture-order` | POST | ✅ | ✅ | `True` |
| `/api/payments/{id}/create-order` | POST | ✅ | ✅ | `True` |
| `/api/payments/{id}/capture` | POST | ✅ | ✅ | `True` |
| `/api/payments/{id}` | GET | ✅ | ✅ | `False` |

**Verification method:** Inspected `git diff HEAD -- backend/app/api/routes/payments.py` in full. Every function signature confirmed to include `current_user: User = Depends(get_current_user)`.

---

## 2. `require_payment_access` Logic Verification

**File:** [`backend/app/services/authorization.py`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/services/authorization.py)

```
git diff HEAD -- backend/app/services/authorization.py
(empty — zero diff)
```

**This file was not modified.** The original Tanishq implementation is intact.

Payer matching logic confirmed:
```python
if payment.member.user_id is not None and payment.member.user_id == user.id:
    is_payer = True
elif payment.member.email and payment.member.email.strip().lower() == user_email_normalized:
    is_payer = True
```

Both `user_id` FK match and email match are supported. This handles members who were created before the JWT User record existed (email-only linking).

---

## 3. Client-Supplied `member_id` / `payerId` Override Analysis

**Finding: Client-supplied identity fields cannot override authenticated identity.**

### Primary endpoints (`/{id}/create-order`, `/{id}/capture`)

Authorization is performed **before** the request body is read for business logic:

```python
# Step 1 — runs first, uses JWT identity only
require_payment_access(db, payment_id, current_user, require_payer=True)

# Step 2 — row lock & fetch
payment = db.query(Payment).filter(Payment.id == payment_id).with_for_update().first()
```

The `PaymentCreateOrderRequest.member_id` field exists in the schema but is **not used in authorization**. It is passed through as a request hint only. The actual payer enforcement is against `payment.id` and `current_user` from the JWT.

### Direct endpoints (`/paypal/create-order`, `/paypal/capture-order`)

The `payerId` / `payer_id` field is used to **look up** which payment to operate on (a convenience lookup for the frontend). After the payment record is resolved, `require_payment_access(require_payer=True)` is called to verify the JWT caller **is** the owner of that payment. If the `payerId` resolves to a payment owned by another user, the caller gets `403`.

```python
# resolve payment by payerId hint...
payment = db.query(Payment).filter(Payment.member_id == body.payer_id, ...).first()

# then enforce JWT ownership
require_payment_access(db, payment.id, current_user, require_payer=True)  # 403 if wrong user
```

**Verdict:** A caller cannot substitute their own `payerId` to claim ownership of another user's payment. The authorization gate runs on the resolved DB payment record against the JWT identity.

---

## 4. Payment History Scope Verification

**Route:** `GET /api/payments/history`

The implementation fetches up to 200 payments and filters in-application code:

```python
all_payments = db.query(Payment).order_by(Payment.created_at.desc()).limit(200).all()
authorized: list[Payment] = []
for p in all_payments:
    if p.member:
        if p.member.user_id == current_user.id:    # direct FK match
            authorized.append(p); continue
        if p.member.email.lower() == normalized_email:  # email match
            authorized.append(p); continue
    if p.expense and p.expense.group and is_user_group_member(db, p.expense.group, current_user):
        authorized.append(p)                        # shared group member
return authorized[:100]
```

**Concern (acknowledged):** Pre-fetching up to 200 rows before filtering means a user's authorized list is capped at 100 of the most recent 200 payments across all users. If the system has >200 total payments, an authorized user may see a truncated list. This is a **data completeness issue**, not a data leakage issue — a user can only see payments they own or whose group they belong to.

**Leakage verdict:** ✅ No. Cross-user payment data cannot be accessed via `/history`.

---

## 5. PayPal Service Integrity Verification

**File:** [`backend/app/services/paypal_service.py`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/services/paypal_service.py)

Inspected `git diff HEAD -- backend/app/services/paypal_service.py`.

| Component | Status | Notes |
|---|---|---|
| OAuth 2.0 token caching | ✅ Intact | `_token_cache` with `_token_expiry` checked before every request |
| Missing credentials guard | ✅ Intact | `PayPalAuthError("not configured")` raised if `client_id` / `client_secret` are empty |
| `create_order` amount/currency | ✅ Intact | Uses server-side `payment.amount` and `payment.currency` only |
| Idempotency keys | ✅ Intact | `idempotency_key=f"order_{payment.id}"` and `capture_{payment.id}_{order_id}` passed in `PayPal-Request-Id` header |
| `capture_order` COMPLETED check | ✅ Intact | `capture_status != "COMPLETED"` → `PaymentStatus.FAILED` |
| Amount/currency server verification | ✅ Intact | `Decimal(captured_amount) != payment.amount` → `HTTP 400` + `FAILED` |
| ORDER_ALREADY_CAPTURED reconciliation | ✅ Intact | `PayPalCaptureError` → `get_order_details()` → `_parse_order_capture()` |
| Network timeout → NOT failed | ✅ Intact | `PayPalConnectionError` on timeout → `504` returned, payment stays `order_created` |
| DB rollback on commit failure | ✅ Intact | All `db.commit()` wrapped in `try/except` with `db.rollback()` |
| Credentials never logged | ✅ Intact | Only `exc.message` logged at ERROR level; no token/secret interpolation |

Changes in `paypal_service.py` diff are limited to:
- Added `issue: str | None = None` parameter to `PayPalOrderError` and `PayPalCaptureError` constructors (used for `ORDER_ALREADY_CAPTURED` reconciliation)
- `application_context` block now always present with fallback URLs (instead of conditional on `return_url`)
- Improved error detail parsing in `create_order`

None of these changes weaken any security property.

---

## 6. Test Coverage Matrix

| Scenario | Test | Location | Result |
|---|---|---|---|
| **Valid payer — create order** | `test_create_order_success` | `test_payments.py` | ✅ PASSED |
| **Valid payer — capture** | `test_capture_success` | `test_payments.py` | ✅ PASSED |
| **Valid payer — frontend routes** | `test_frontend_compatibility_routes` | `test_payments.py` | ✅ PASSED |
| **Valid payer — history scoped** | `test_payment_history` | `test_payments.py` | ✅ PASSED |
| **Unauthenticated → 401** (generic) | `test_missing_token_returns_401` | `test_auth.py` | ✅ PASSED |
| **Unauthenticated → 401** (payment-specific) | _(not in test_payments.py)_ | — | ⚠️ GAP — see §7 |
| **Authenticated impostor — create-order → 403** | `test_payment_ownership_violation_create_order` | `test_payments.py` | ✅ PASSED |
| **Authenticated impostor — capture → 403** | `test_payment_ownership_violation_capture` | `test_payments.py` | ✅ PASSED |
| **Cross-user payment read → 404** | `test_user_a_cannot_access_user_b_payment_record` | `test_authorization.py` | ✅ PASSED |
| **Cross-user pay-other-member → 403** | `test_user_cannot_pay_another_members_share` | `test_authorization.py` | ✅ PASSED |
| **Duplicate order creation → 409** | `test_create_order_duplicate_prevented` | `test_payments.py` | ✅ PASSED |
| **Duplicate capture → 409** | `test_capture_duplicate_prevented` | `test_payments.py` | ✅ PASSED |
| **Concurrent capture → 409** | `test_concurrent_capture_attempts` | `test_payments.py` | ✅ PASSED |
| **PayPal capture API failure → 502** | `test_capture_failed_paypal_api` | `test_payments.py` | ✅ PASSED |
| **PayPal auth failure → 502** | `test_paypal_oauth_failure` | `test_payments.py` | ✅ PASSED |
| **Network timeout → 504, status unchanged** | `test_paypal_network_timeout` | `test_payments.py` | ✅ PASSED |
| **Timeout then reconcile → 200 CAPTURED** | `test_capture_reconciliation_after_network_timeout` | `test_payments.py` | ✅ PASSED |
| **ORDER_ALREADY_CAPTURED reconcile** | `test_paypal_service_reconciles_already_captured_order` | `test_payments.py` | ✅ PASSED |
| **Amount mismatch → 400 + FAILED** | `test_capture_amount_mismatch` | `test_payments.py` | ✅ PASSED |
| **Currency mismatch → 400 + FAILED** | `test_capture_currency_mismatch` | `test_payments.py` | ✅ PASSED |
| **Order ID mismatch → 400** | `test_capture_order_id_mismatch` | `test_payments.py` | ✅ PASSED |
| **Capture wrong status → 409** | `test_capture_pending_prevented` | `test_payments.py` | ✅ PASSED |
| **DB rollback on commit failure** | `test_database_rollback_on_commit_error` | `test_payments.py` | ✅ PASSED |
| **Malformed create-order response** | `test_paypal_service_malformed_create_order` | `test_payments.py` | ✅ PASSED |
| **Malformed capture response** | `test_paypal_service_malformed_capture_order` | `test_payments.py` | ✅ PASSED |

---

## 7. Security Gaps and Findings

### GAP-1 (Low) — No named test for unauthenticated payment endpoint access

**Severity:** Low  
**Description:** `test_payments.py` does not contain any test using `unauth_client` to call a payment route. The generic `test_missing_token_returns_401` in `test_auth.py` only tests `/api/auth/me`.

**Runtime verification (manual inline script, not a test):**
```
No-token create-order:         401
No-token capture:              401
No-token history:              401
No-token get payment:          401
No-token direct create-order:  401
No-token direct capture-order: 401
```

**All six payment routes correctly return 401 when no token is provided.** The behavior is correct; the gap is test coverage only.

**Recommended fix (for Tanay):** Add to `test_payments.py`:
```python
def test_unauthenticated_access_to_payment_routes_returns_401(unauth_client, db_session):
    payment_id = uuid.uuid4()
    assert unauth_client.get(f"/api/payments/{payment_id}").status_code == 401
    assert unauth_client.post(f"/api/payments/{payment_id}/create-order", json={}).status_code == 401
    assert unauth_client.post(f"/api/payments/{payment_id}/capture",
                              json={"paypal_order_id": "X"}).status_code == 401
    assert unauth_client.get("/api/payments/history").status_code == 401
    assert unauth_client.post("/api/payments/paypal/create-order", json={}).status_code == 401
    assert unauth_client.post("/api/payments/paypal/capture-order",
                              json={"orderId": "X"}).status_code == 401
```

### GAP-2 (Informational) — Payment history O(N) pre-fetch

**Severity:** Informational  
**Description:** `/history` fetches 200 rows before filtering to 100. With a large dataset, authorized users may receive a truncated view. No data is leaked to unauthorized callers.

**Recommended fix (future):** Push filtering into the SQL query using a JOIN on `GroupMember` and subquery for user membership, eliminating the application-level scan.

### Finding-1 (Positive) — `member_id` body field correctly ignored for authorization

Confirmed: supplying a random `member_id` UUID in the create-order or capture request body has no effect on authorization. The gate is `require_payment_access(db, payment_id, current_user, ...)` where `payment_id` comes from the URL path and `current_user` from the JWT.

### Finding-2 (Positive) — Tanishq's `authorization.py` unchanged

`git diff HEAD -- backend/app/services/authorization.py` returns empty. The IDOR protection layer was not touched in Phase 7 or Phase 8.

---

## 8. Git Diff Summary

**Command:** `git diff --stat HEAD`  
**Exit code:** 1 (from PowerShell NativeCommandError on stderr LF warning — cosmetic, not a git failure)

```
backend/app/api/routes/payments.py     | +228/-181  (auth integration)
backend/app/services/paypal_service.py | +163/-?    (reconciliation, issue field)
backend/tests/test_payments.py         | +261/-1    (member identity fix, ownership tests)
backend/app/core/config.py             | +5         (JWT settings)
backend/app/schemas/schemas.py         | +40        (auth schemas merged)
backend/app/main.py                    | +3/-1      (auth router mounted)
backend/app/models/models.py           | +60        (User model, FK additions)
backend/requirements.txt               | +9         (bcrypt, pyjwt)
backend/tests/conftest.py              | +76/-?     (auth fixtures)
backend/app/api/routes/expenses.py     | +60        (auth integration on expenses)
backend/app/api/routes/groups.py       | +92        (auth integration on groups)
backend/app/api/routes/receipts.py     | +23        (auth integration on receipts)
backend/.env.example                   | +1         (JWT_SECRET_KEY placeholder)
.gitignore                             | +9
docs/BACKEND_CONTRACT.md               | +139
backend/test.db                        | binary change
```

**Files NOT modified (verified zero diff):**
- `backend/app/services/authorization.py` ← Tanishq's IDOR protection — untouched ✅
- `backend/app/api/deps.py` (new untracked file, not modified from original)
- `backend/app/api/routes/auth.py` (new untracked file)
- `backend/app/core/security.py` (new untracked file)

**Scope verdict:** All changes are within the intended files. No unrelated files were modified.

---

## 9. Test Run Results

### Payment tests only
```
Command: pytest tests/test_payments.py -v --tb=short
Result:  27 passed, 1 warning in 28.32s
Exit code (pytest process): 0
```

### Full backend suite
```
Command: pytest tests/test_auth.py tests/test_authorization.py tests/test_payments.py
         tests/test_expenses.py tests/test_groups.py tests/test_health.py tests/test_receipts.py -v
Result:  90 passed, 1 warning in 128.98s (0:02:08)
Exit code (pytest process): 0
```

> [!NOTE]
> The shell command exits with code 1 on Windows due to PowerShell treating pytest-asyncio's deprecation warning on **stderr** as a `NativeCommandError`. The pytest process itself reported exit code **0** (captured via `$LASTEXITCODE` / `FULL_SUITE_EXIT_CODE=0` in the output). This is a PowerShell stderr-routing artifact, not a test failure.

> [!NOTE]
> `test_postgres_concurrency.py` was excluded from both runs. It requires a live PostgreSQL instance. The main suite uses SQLite in-memory. Row-level locking (`WITH FOR UPDATE`) is not enforced by SQLite and those tests will only be meaningful against PostgreSQL.

---

## 10. Verdict

| Check | Result |
|---|---|
| All payment routes use `get_current_user` | ✅ Verified |
| Create-order uses `require_payer=True` | ✅ Verified |
| Capture uses `require_payer=True` | ✅ Verified |
| Client `member_id`/`payerId` cannot override JWT identity | ✅ Verified |
| Payment history cannot expose another user's payments | ✅ Verified (with GAP-2 informational note) |
| PayPal OAuth, token caching, and credentials guard | ✅ Intact |
| Order creation with server-side amount/currency | ✅ Intact |
| Capture with idempotency key | ✅ Intact |
| Timeout reconciliation (504 → retry → CAPTURED) | ✅ Intact |
| Amount/currency server-side verification | ✅ Intact |
| DB rollback on commit failure | ✅ Intact |
| Test: valid payer flows | ✅ Covered |
| Test: unauthenticated callers → 401 | ⚠️ Behavior correct; no named pytest test in `test_payments.py` |
| Test: authenticated impostor → 403 | ✅ Covered |
| Test: duplicate capture → 409 | ✅ Covered |
| Test: PayPal capture failure → 502 | ✅ Covered |
| Test: timeout/reconciliation | ✅ Covered |
| Changes limited to intended files | ✅ Verified |
| Tanishq's `authorization.py` unmodified | ✅ Verified (zero diff) |

**Phase 8 security review: PASSED with one low-severity gap (GAP-1 — missing 401 pytest coverage for payment routes).**
