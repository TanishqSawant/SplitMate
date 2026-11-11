# SplitMate PayPal Integration — Phase 5 Verification Report

**Document:** `PAYPAL_PHASE5_VERIFICATION.md`  
**Role:** Tanay – PayPal Integration Lead  
**Collaborators:** Dhruv (Frontend Lead), Tanishq (Backend Architecture Lead)  
**Date:** November 10, 2026  
**Git Branch:** `feature/paypal-sandbox`  
**Overall Readiness Verdict:** 🟡 **SANDBOX READY / PRODUCTION BLOCKED**

---

> [!CAUTION]
> **Production Readiness Statement:**  
> The PayPal Sandbox integration is fully implemented, hardened, and test-verified for sandbox testing and demo flows. **However, it is NOT production-ready.** The backend currently lacks cryptographic user authentication (no JWT or session verification). Client-supplied `member_id` and `payerId` parameters cannot prove caller identity. Production deployment must remain blocked until Tanishq implements trusted authentication.

---

## 1. Contract vs. Actual Source Code Audit

A line-by-line comparison between [`docs/PAYPAL_REACT_INTEGRATION_CONTRACT.md`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/docs/PAYPAL_REACT_INTEGRATION_CONTRACT.md) and the backend codebase:

| Contract Specification | Actual Implementation File & Line | Status | Notes |
|------------------------|-----------------------------------|--------|-------|
| `POST /api/payments/{payment_id}/create-order` | [`backend/app/api/routes/payments.py#L127`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L127) | ✅ Exact Match | Uses DB amount/currency; row-level lock; returns `PaymentResponse`. |
| `POST /api/payments/{payment_id}/capture` | [`backend/app/api/routes/payments.py#L232`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L232) | ✅ Exact Match | Verifies order ID, capture status `COMPLETED`, amount & currency. |
| `POST /api/payments/paypal/create-order` | [`backend/app/api/routes/payments.py#L52`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L52) | ✅ Exact Match | Static compatibility route defined before dynamic routes. |
| `POST /api/payments/paypal/capture-order` | [`backend/app/api/routes/payments.py#L91`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L91) | ✅ Exact Match | Resolves payment by `order_id` or `payment_id`. |
| `GET /api/payments/{payment_id}` | [`backend/app/api/routes/payments.py#L418`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L418) | ✅ Exact Match | Returns current payment record. |
| `GET /api/payments/history` | [`backend/app/api/routes/payments.py#L42`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L42) | ✅ Exact Match | Returns latest 100 payments, newest first. |
| `POST /api/expenses/{expense_id}/initialize-payments` | [`backend/app/api/routes/expenses.py#L231`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/expenses.py#L231) | ✅ Exact Match | Calculates item splits, tax/fees, penny rounding; creates pending payments. |
| `PaymentCreateOrderRequest` | [`backend/app/schemas/schemas.py#L182`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/schemas/schemas.py#L182) | ✅ Exact Match | `member_id: UUID | None`, `return_url`, `cancel_url`. |
| `PaymentCaptureRequest` | [`backend/app/schemas/schemas.py#L189`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/schemas/schemas.py#L189) | ✅ Exact Match | `paypal_order_id: str (max 50)`, `member_id: UUID | None`. |
| `PaymentDirectCreateOrderRequest` | [`backend/app/schemas/schemas.py#L211`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/schemas/schemas.py#L211) | ✅ Exact Match | Aliases: `paymentId`, `payerId`, `expenseId`, `receiverEmail`. |
| `PaymentDirectCaptureRequest` | [`backend/app/schemas/schemas.py#L225`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/schemas/schemas.py#L225) | ✅ Exact Match | Aliases: `orderId`, `paymentId`, `payerId`. |
| `PaymentResponse` | [`backend/app/schemas/schemas.py#L195`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/schemas/schemas.py#L195) | ✅ Exact Match | Contains `paypal_order_id`, `paypal_capture_id`, `status`, `approval_url`. |
| PayPal Service Methods | [`backend/app/services/paypal_service.py`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/services/paypal_service.py) | ✅ Exact Match | Implements `get_access_token`, `create_order`, `capture_order`, `get_order_details`. |

---

## 2. Pydantic Alias & Serialization Verification

### Objective
Verify that `paymentId` supports frontend camelCase input without breaking existing snake_case clients (`payment_id`) or causing response serialization collisions.

### Test Execution & Results
Direct programmatic validation executed against Python 3.12:
```python
from uuid import uuid4
from app.schemas.schemas import PaymentDirectCreateOrderRequest, PaymentDirectCaptureRequest

uid = uuid4()

# 1. CamelCase input
req_camel = PaymentDirectCreateOrderRequest.model_validate({'paymentId': str(uid), 'payerId': str(uid)})
assert req_camel.payment_id == uid
assert req_camel.payer_id == uid

# 2. Snake_case input
req_snake = PaymentDirectCreateOrderRequest.model_validate({'payment_id': str(uid), 'payer_id': str(uid)})
assert req_snake.payment_id == uid
assert req_snake.payer_id == uid

# 3. Capture CamelCase and Snake_case
cap_camel = PaymentDirectCaptureRequest.model_validate({'orderId': 'ORD123', 'paymentId': str(uid)})
assert cap_camel.order_id == 'ORD123' and cap_camel.payment_id == uid

cap_snake = PaymentDirectCaptureRequest.model_validate({'order_id': 'ORD123', 'payment_id': str(uid)})
assert cap_snake.order_id == 'ORD123' and cap_snake.payment_id == uid
```
**Result:** Passed without warnings.  
- `populate_by_name = True` guarantees that incoming JSON with either `paymentId` or `payment_id` populates `payment_id`.
- Neither `PaymentDirectCreateOrderRequest` nor `PaymentDirectCaptureRequest` is used as a response model; responses use `PaymentResponse` which consistently outputs standard snake_case fields (`id`, `expense_id`, `member_id`, `paypal_order_id`, `paypal_capture_id`).

---

## 3. Automated Test Execution Report

Tests were executed as two independent runs to isolate payment business logic from database dialect concurrency tests.

### Test Run 1: Payment Test Suite
- **Exact Command:**
  ```powershell
  cd C:\Users\HP\Desktop\SplitMate\SplitMate\backend; .\.venv\Scripts\pytest.exe tests/test_payments.py -v; Write-Host "PYTEST_EXIT_CODE: $LASTEXITCODE"
  ```
- **Summary:**
  - `27 passed, 1 warning in 19.56s`
  - Warning: Deprecation warning in `starlette.testclient` regarding `anyio.abc.BlockingPortal`.
- **Actual Process Exit Code:** `0`
- **Tests Skipped:** None (`0 skipped`).
- **Database Used:** Local SQLite test harness.

### Test Run 2: PostgreSQL Concurrency Test Suite
- **Exact Command:**
  ```powershell
  cd C:\Users\HP\Desktop\SplitMate\SplitMate\backend; .\.venv\Scripts\pytest.exe tests/test_postgres_concurrency.py -v -rs; Write-Host "PYTEST_EXIT_CODE: $LASTEXITCODE"
  ```
- **Summary:**
  - `1 passed, 1 skipped, 1 warning in 0.09s`
- **Actual Process Exit Code:** `0`
- **Tests Skipped & Reason:**
  - `tests/test_postgres_concurrency.py::test_live_postgres_concurrent_capture_lock`: **SKIPPED**
  - **Skip Reason:** `TEST_POSTGRESQL_URL environment variable not set; skipping live PostgreSQL concurrency test.`
- **Real PostgreSQL Instance Used:** **No.** Tests run against SQLite. The passed test (`test_postgresql_dialect_generates_for_update`) statically verifies that SQLAlchemy's PostgreSQL dialect compiles queries with `FOR UPDATE`. The live two-connection row-locking test is designed to run only when an actual PostgreSQL URL is supplied.

---

## 4. Payment Authorization & Identity Audit

An exhaustive audit of every endpoint accepting `member_id` or `payerId`:

| Endpoint | Parameter | Location | How Identity is Handled | Cryptographically Verified? |
|----------|-----------|----------|-------------------------|------------------------------|
| `POST /api/payments/{payment_id}/create-order` | `member_id: UUID \| None` | JSON Body | If provided, backend asserts `payment.member_id == body.member_id`. If omitted, skipped. | ❌ **NO.** Client-supplied only. |
| `POST /api/payments/{payment_id}/capture` | `member_id: UUID \| None` | JSON Body | If provided, backend asserts `payment.member_id == body.member_id`. If omitted, skipped. | ❌ **NO.** Client-supplied only. |
| `POST /api/payments/paypal/create-order` | `payerId: UUID \| None` | JSON Body | Used as fallback filter to locate `Payment` row; forwarded to `create_paypal_order`. | ❌ **NO.** Client-supplied only. |
| `POST /api/payments/paypal/capture-order` | `payerId: UUID \| None` | JSON Body | Forwarded to `capture_payment` as `member_id`. | ❌ **NO.** Client-supplied only. |
| `POST /api/expenses/{expense_id}/assign` | `assignments[].member_id` | JSON Body | Validates that member exists and belongs to the expense's group. | ❌ **NO.** Client-supplied only. |
| `POST /api/groups/{group_id}/members` | `email`, `name` | JSON Body | Adds member to group without verifying owner/creator identity. | ❌ **NO.** Anyone can add members. |

### Security Assessment
1. **No Authenticated User Model**: The backend has no `User` model, password hashing, or token verification.
2. **Relational Consistency vs. Identity**: The backend successfully enforces *relational integrity* (payments must match the expense's group, and payments cannot be created or captured under another member's ID if `member_id` is passed). However, because there is no cryptographic signature (JWT/session cookie), **any HTTP client can impersonate any member ID**.
3. **Frontend Context Vulnerability**: In `frontend/src/context/AuthContext.jsx`, user identity is chosen via a mock dropdown in `localStorage`.
4. **Conclusion**: Identity verification is an architectural dependency on Tanishq. Until JWT authentication is added, the system cannot be considered production-secure.

---

## 5. Server-Side Financial & Ownership Verification Guarantees

The backend confirms all critical verification steps before committing financial records:

### 1. Amount & Currency Integrity
- During order creation, the backend queries `payment.amount` and `payment.currency` directly from the database ([`payments.py#L186-L187`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L186-L187)). Any amount sent in the frontend request body is discarded.
- During capture, the backend parses PayPal's capture payload ([`payments.py#L358-L399`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L358-L399)):
  - Asserts `captured_amount == payment.amount` (casts to `Decimal`).
  - Asserts `captured_currency == payment.currency.upper()`.
  - On mismatch, commits status `FAILED` and raises `HTTP 400 Bad Request`.

### 2. Group & Payment Ownership
- Asserts `payment.expense.group_id == payment.member.group_id` ([`payments.py#L159-L163`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L159-L163)).
- Cross-group manipulations are rejected with `HTTP 403 Forbidden`.

### 3. Capture Status Enforcement
- Asserts PayPal capture status is strictly `"COMPLETED"` ([`payments.py#L344-L354`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L344-L354)).
- Rejected captures transition the record to `FAILED` and raise `HTTP 400 Bad Request`.

### 4. Concurrency & Duplicate Protection
- Uses `with_for_update()` on payment lookups to serialize concurrent requests.
- Immediate rejection with `HTTP 409 Conflict` if status is already `CAPTURED`.
- Passes deterministic `PayPal-Request-Id` idempotency keys (`order_{payment.id}`, `capture_{payment.id}_{order_id}`).
- Automatic reconciliation: if PayPal reports `ORDER_ALREADY_CAPTURED`, the backend queries `get_order_details()` to verify completion before marking `CAPTURED` ([`paypal_service.py#L291-L300`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/services/paypal_service.py#L291-L300)).
- Network timeouts (`504 Gateway Timeout`) preserve status as `order_created` so that status reconciliation can safely occur without double-charging or premature failure.

---

## 6. Git Working Tree & Diff Review

### Git Status
```
On branch feature/paypal-sandbox
Your branch is up to date with 'origin/feature/paypal-sandbox'.

Changes not staged for commit:
	modified:   backend/.env.example
	modified:   backend/app/api/routes/payments.py
	modified:   backend/app/schemas/schemas.py
	modified:   backend/app/services/paypal_service.py
	modified:   backend/tests/test_payments.py

Untracked files:
	backend/tests/test_postgres_concurrency.py
	docs/PAYPAL_PHASE5_VERIFICATION.md
	docs/PAYPAL_REACT_INTEGRATION_CONTRACT.md

no changes added to commit
```

### Git Diff Summary
- **`backend/.env.example`**: Added `PAYPAL_TIMEOUT_SECONDS=10`.
- **`backend/app/api/routes/payments.py`**:
  - Reordered static routes (`/history`, `/paypal/...`) before `/{payment_id}`.
  - Added `with_for_update()` row locking.
  - Added group membership validation & optional caller authorization.
  - Added explicit `db.rollback()` on all exception pathways.
  - Added timeout and `ORDER_ALREADY_CAPTURED` recovery logic.
- **`backend/app/schemas/schemas.py`**:
  - Added `member_id` to request schemas.
  - Added `approval_url` to `PaymentResponse`.
  - Added `paymentId` aliases to direct compatibility schemas with `populate_by_name = True`.
- **`backend/app/services/paypal_service.py`**:
  - Full OAuth 2.0 client credentials token caching.
  - Orders v2 creation with idempotency keys.
  - Capture v2 with automatic `ORDER_ALREADY_CAPTURED` reconciliation.
  - Added `get_order_details()` helper.
- **`backend/tests/test_payments.py`**: Added 27 tests covering OAuth failures, capture timeouts, currency/amount mismatches, rollback, and concurrency.
- **`backend/tests/test_postgres_concurrency.py`**: Untracked concurrency test file.
- **`docs/PAYPAL_REACT_INTEGRATION_CONTRACT.md`**: Untracked frontend-backend contract.
- **State Check**: No files staged, no commits made, no push executed.

---

## 7. Actionable Recommendations

### For Tanay (PayPal Integration Lead)
1. **Sandbox Testing**: Once Dhruv removes frontend mocks, perform end-to-end sandbox checkouts using facilitator and buyer credentials.
2. **PostgreSQL Staging Run**: Set `TEST_POSTGRESQL_URL` in a staging environment to run the live concurrent lock test (`test_live_postgres_concurrent_capture_lock`).

### For Dhruv (Frontend Lead)
1. **Delete Mock Interceptors**: Remove lines 205–229 in `frontend/src/api/client.js` so requests reach FastAPI.
2. **Switch to `@paypal/react-paypal-js`**: Follow the pseudocode pattern in [`docs/PAYPAL_REACT_INTEGRATION_CONTRACT.md`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/docs/PAYPAL_REACT_INTEGRATION_CONTRACT.md).
3. **Response Key Consumption**: Read `paypal_order_id` and `paypal_capture_id` from backend responses (not `orderId` or `captureId`).
4. **Trigger Pre-Payment Initialization**: Ensure `POST /api/expenses/{expense_id}/initialize-payments` is called once item assignments are finalized.

### For Tanishq (Backend Architecture Lead)
1. **User Authentication (Critical Blocker for Production)**:
   - Create a `users` table and implement JWT authentication (`/api/auth/login`, `/api/auth/register`).
   - Link `GroupMember.user_id` to `users.id`.
   - Replace `body.member_id` authorization hints with an authenticated FastAPI dependency:
     ```python
     @router.post("/{payment_id}/create-order")
     def create_paypal_order(
         payment_id: uuid.UUID,
         current_user: User = Depends(get_current_user),
         ...
     ):
         if payment.member.user_id != current_user.id:
             raise HTTPException(status_code=403, detail="Forbidden")
     ```
2. **PostgreSQL Migration**: Ensure production migrations apply row-level locking (`with_for_update()`) on PostgreSQL instances.

