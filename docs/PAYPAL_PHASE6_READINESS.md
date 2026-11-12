# SplitMate — Phase 6: PayPal Integration Readiness Guide

**Document:** `PAYPAL_PHASE6_READINESS.md`  
**Role:** Tanay – PayPal Integration Lead  
**Collaborators:** Dhruv (Frontend Lead), Tanishq (Backend Architecture Lead)  
**Date:** November 10, 2026  
**Git Branch:** `feature/paypal-sandbox`  
**Target Event:** PayPal AI Hackathon (Deadline: November 13, 2026)  
**Current Status:** 🟡 **SANDBOX READY / AWAITING LIVE CREDENTIALS & FRONTEND SDK HOOKUP**

---

> [!IMPORTANT]
> **Live Testing Baseline:**  
> The backend PayPal implementation has passed **28/28 automated unit, security, and concurrency tests** with mocked PayPal endpoints. Live PayPal Sandbox transactions will succeed once real Sandbox API credentials are configured in `backend/.env` and Dhruv hooks up real buyer approval in the React frontend. **No claim of live payment success is made until an actual Sandbox transaction is processed end-to-end.**

---

## 1. Backend Implementation Readiness Assessment

The PayPal backend implementation is audited and verified against PayPal Orders API v2:

| Component | Implementation File | Verification Status | Operational Guarantees |
|-----------|---------------------|---------------------|------------------------|
| **OAuth 2.0 Auth** | [`paypal_service.py#L93-L148`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/services/paypal_service.py#L93-L148) | ✅ Production Grade | Basic auth grant, in-memory token caching with 60s expiration buffer, zero credential logging. |
| **Create Order** | [`paypal_service.py#L150-L277`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/services/paypal_service.py#L150-L277) | ✅ Production Grade | `intent: "CAPTURE"`, 2-decimal formatting, `PayPal-Request-Id` idempotency header, `approval_url` parsing. |
| **Capture Order** | [`paypal_service.py#L317-L412`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/services/paypal_service.py#L317-L412) | ✅ Production Grade | Auto-reconciliation on `ORDER_ALREADY_CAPTURED`, extracts capture ID, amount, currency, and status. |
| **Order Details** | [`paypal_service.py#L414-L440`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/services/paypal_service.py#L414-L440) | ✅ Production Grade | `GET /v2/checkout/orders/{id}` query for idempotent status verification. |
| **Route Security** | [`payments.py#L127-L416`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L127-L416) | ✅ Production Grade | `with_for_update()` row locks, database amount/currency enforcement, group integrity validation, explicit rollbacks. |
| **Compatibility** | [`payments.py#L52-L121`](file:///C:/Users/HP/Desktop/SplitMate/SplitMate/backend/app/api/routes/payments.py#L52-L121) | ✅ Production Grade | Static compatibility endpoints accepting both camelCase (`paymentId`, `payerId`) and snake_case aliases. |

---

## 2. Repeatable End-to-End Sandbox Test Checklist

Follow these exact steps to execute a complete, repeatable live Sandbox transaction:

```
[1. Initialize Payments] ──▶ [2. Create PayPal Order] ──▶ [3. Receive Approval URL/ID]
                                                                     │
[6. Verify Capture]      ◀── [5. Capture Payment]     ◀── [4. Buyer Approval in Sandbox]
       │
       ▼
[7. Verify Amount/Currency] ──▶ [8. Verify History & Balances]
```

### Step 1: Initialize Expense Payments
- **Action:** After receipt extraction and item assignment, call:
  ```http
  POST /api/expenses/{expense_id}/initialize-payments
  ```
- **Expected Result:**
  - HTTP `201 Created`
  - Returns `list[PaymentResponse]`.
  - Each record has: `status: "pending"`, `amount: <calculated_share>`, `currency: "USD"`, `paypal_order_id: null`.
  - Record the returned `id` (the `payment_id`).

### Step 2: Create PayPal Order
- **Action:** Debtor triggers checkout:
  ```http
  POST /api/payments/{payment_id}/create-order
  Content-Type: application/json

  {
    "member_id": "<debtor_member_uuid>"
  }
  ```
  *(Or via compatibility route `POST /api/payments/paypal/create-order` with `{ paymentId: "..." }`).*
- **Expected Result:**
  - HTTP `200 OK`
  - Response contains `status: "order_created"`.
  - Response contains a valid PayPal order ID: `paypal_order_id: "5O190127TN364715T"`.
  - Response contains `approval_url: "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T"`.
  - Database row status is now `order_created` and `paypal_order_id` is persisted.

### Step 3: Receive Approval URL / Order ID
- **Action:**
  - Frontend SDK receives `paypal_order_id` in `createOrder` callback.
  - Or frontend opens `approval_url` in a popup/new window for the buyer.

### Step 4: Buyer Approval in PayPal Sandbox
- **Action:**
  - Tester logs into PayPal Sandbox using the **Buyer Sandbox Account** (e.g., `buyer@personal.example.com`).
  - Tester reviews the exact amount matching the split share.
  - Tester clicks **"Complete Purchase"** or **"Pay Now"**.
- **Expected Result:**
  - PayPal approves the order and triggers `onApprove({ orderID: "5O190127TN364715T" })` in the SDK.
  - Order status on PayPal is now `APPROVED`.

### Step 5: Backend Payment Capture
- **Action:** Frontend calls backend capture endpoint:
  ```http
  POST /api/payments/{payment_id}/capture
  Content-Type: application/json

  {
    "paypal_order_id": "5O190127TN364715T",
    "member_id": "<debtor_member_uuid>"
  }
  ```
- **Expected Result:**
  - HTTP `200 OK`
  - Backend executes `POST /v2/checkout/orders/{id}/capture` against PayPal with idempotency key `capture_{payment_id}_{order_id}`.

### Step 6: Verify Capture Status is COMPLETED
- **Action:** Inspect response JSON:
  - `status` MUST be `"captured"`.
  - `paypal_capture_id` MUST be populated (e.g. `"1AB23456CD789012E"`).

### Step 7: Verify Amount & Currency Against Database
- **Backend Verification Guarantee:**
  - Backend verifies that PayPal's `captured_amount == payment.amount` and `captured_currency == payment.currency`.
  - If any mismatch occurs, backend transitions payment to `failed` and returns HTTP `400 Bad Request`.
- **Expected Result:** Payment record in DB has `status = 'captured'` and `paypal_capture_id` recorded.

### Step 8: Verify Payment History & Balances
- **Action:**
  ```http
  GET /api/payments/{payment_id}
  GET /api/payments/history
  GET /api/groups/{group_id}/balances
  ```
- **Expected Result:**
  - Payment record displays status `captured` with timestamp.
  - Group debt balance between debtor and creditor is reduced by the captured payment amount.

---

## 3. Required Sandbox Credentials & Environment Variables

> [!CAUTION]
> **Zero Exposure Rule:** Never commit, print, log, or share `PAYPAL_CLIENT_SECRET`.

### Backend Configuration (`backend/.env`)

```ini
# Database (PostgreSQL for staging/production; SQLite for local test)
DATABASE_URL=postgresql://splitmate_user:your_password@localhost:5432/splitmate_db

# Application Mode
APP_ENV=development
DEBUG=true

# CORS Origins (allow Vite dev server)
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# PayPal Sandbox API (Obtained from developer.paypal.com)
PAYPAL_CLIENT_ID=your_sandbox_client_id_here
PAYPAL_CLIENT_SECRET=your_sandbox_client_secret_here
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_TIMEOUT_SECONDS=10
```

### Frontend Configuration (`frontend/.env`)

```ini
# Backend API Base URL
VITE_API_BASE_URL=http://localhost:8000/api

# Disable mock fallback so requests reach FastAPI
VITE_USE_MOCK_API=false

# Public-safe PayPal Sandbox Client ID (identical to PAYPAL_CLIENT_ID)
VITE_PAYPAL_CLIENT_ID=your_sandbox_client_id_here
```

### Sandbox Accounts Needed from Developer Dashboard
1. **Facilitator (Business Account)**:
   - Account email: `facilitator-splitmate@business.example.com`
   - Purpose: Linked to the REST API app; receives Sandbox funds.
2. **Buyer (Personal Account)**:
   - Account email: `buyer-splitmate@personal.example.com`
   - Purpose: Used by judges/testers during the live demo to log into the PayPal checkout modal and approve payments with simulated funds.

---

## 4. Frontend/Backend Integration Dependencies & Gaps

The following four gaps must be addressed for live end-to-end checkout:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🔴 CRITICAL INTEGRATION GAPS                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Simulated setTimeout(700) in ExpenseContext.jsx:                         │
│    ExpenseContext.jsx calls capture-order after 700ms without buyer         │
│    approval. Live PayPal Sandbox will reject this with ORDER_NOT_APPROVED.  │
│    Fix: Replace with @paypal/react-paypal-js <PayPalButtons> onApprove hook.│
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Frontend Field Mismatches:                                              │
│    ExpenseContext.jsx reads order.orderId & capture.captureId (camelCase).  │
│    Backend returns paypal_order_id & paypal_capture_id (snake_case).        │
│    Fix: Update frontend to consume snake_case keys.                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. Missing Cryptographic Authentication (Tanishq):                          │
│    No JWT verification exists. member_id is a client-supplied hint.         │
│    Production blocked; acceptable for Sandbox demo with cooperative users.  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4. Pre-Payment Initialization Trigger:                                      │
│    Frontend currently calculates shares in local state; it must invoke      │
│    POST /api/expenses/{id}/initialize-payments to create pending rows.     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Review of Modified & Untracked Files

All files in the working directory remain safely unstaged on `feature/paypal-sandbox`:

```
On branch feature/paypal-sandbox
Your branch is up to date with 'origin/feature/paypal-sandbox'.

Changes not staged for commit:
  backend/.env.example                        # Added PAYPAL_TIMEOUT_SECONDS=10
  backend/app/api/routes/payments.py          # Hardened endpoints, row locks, reconciliation
  backend/app/schemas/schemas.py              # Added member_id, approval_url, paymentId aliases
  backend/app/services/paypal_service.py      # OAuth2 token caching, Orders v2, capture reconciliation
  backend/tests/test_payments.py              # 27 comprehensive tests (timeouts, locks, mismatches)

Untracked files:
  backend/tests/test_postgres_concurrency.py  # Dialect concurrency & row-locking test
  docs/PAYPAL_PHASE5_VERIFICATION.md          # Verification findings & security audit report
  docs/PAYPAL_PHASE6_READINESS.md             # This readiness guide
  docs/PAYPAL_REACT_INTEGRATION_CONTRACT.md   # Formal contract for Dhruv

no changes added to commit (0 files staged)
```

---

## 6. Demo-Day Troubleshooting & Contingency Playbook

### Scenario 1: PayPal Sandbox API Latency or Network Timeout (HTTP 504)
- **Symptom:** Spinner spins for 10 seconds; frontend receives `504 Gateway Timeout`.
- **Root Cause:** PayPal Sandbox network latency spike.
- **Backend Safety Guarantee:** Payment status **remains `order_created`**; backend does NOT fail the payment.
- **Troubleshooting Action:**
  1. Do not panic or re-create the order.
  2. Click "Verify Payment Status" or trigger a capture retry with the same `paypal_order_id`.
  3. The backend capture logic includes automatic `ORDER_ALREADY_CAPTURED` reconciliation: it queries PayPal order details and recovers the completed capture state safely.

### Scenario 2: Buyer Cancels Checkout (Popup Closed)
- **Symptom:** Buyer closes the PayPal Sandbox window or clicks "Cancel and return to SplitMate".
- **Expected Behavior:** `onCancel(data)` callback fires in React.
- **Troubleshooting Action:**
  1. Frontend catches `onCancel` and resets modal state to `idle`.
  2. Display: "Payment cancelled. No funds were debited."
  3. The payment record remains in `order_created` or `pending` and can be re-attempted.

### Scenario 3: "ORDER_NOT_APPROVED" Error (HTTP 400 / 502)
- **Symptom:** Capture endpoint returns `400 Bad Request` with `ORDER_NOT_APPROVED`.
- **Root Cause:** Capture was called before the buyer logged into Sandbox and clicked "Pay Now". (Usually caused by the legacy 700ms `setTimeout` in `ExpenseContext.jsx`).
- **Troubleshooting Action:**
  1. Verify buyer completed approval on PayPal.
  2. Ensure capture is ONLY called inside the SDK's `onApprove` callback.

### Scenario 4: Invalid Client Credentials (HTTP 502)
- **Symptom:** `502 Bad Gateway: PayPal authentication failure`.
- **Root Cause:** Mismatched `PAYPAL_CLIENT_ID` or `PAYPAL_CLIENT_SECRET` in `backend/.env`.
- **Troubleshooting Action:**
  1. Check `backend/.env` for trailing whitespace or quotes around keys.
  2. Verify that `PAYPAL_BASE_URL` is `https://api-m.sandbox.paypal.com` (not live production).
  3. Restart the FastAPI server (`uvicorn app.main:app --reload`).

### Scenario 5: Demo Reset (Quick Database Reset)
- **Action:** If demo state becomes corrupted during practice runs:
  ```powershell
  # For SQLite local dev:
  Remove-Item backend/test.db -Force
  # Re-run test suite or start app to regenerate clean database
  ```

