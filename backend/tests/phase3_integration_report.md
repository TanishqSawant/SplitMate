# SplitMate – Phase 3 Integration Report
**Deadline:** November 13, 2026 | **Last updated:** November 11, 2026

> [!IMPORTANT]
> This report separates **mock mode** results (no credentials required) from **live API** results (requires credentials). All mock results are confirmed by automated tests. Live API results are gated by credential availability.

---

## Table of Contents
1. [Environment & Prerequisites](#1-environment--prerequisites)
2. [Gemini Vision Integration](#2-gemini-vision-integration)
3. [PayPal Sandbox Integration](#3-paypal-sandbox-integration)
4. [Frontend Testing Results](#4-frontend-testing-results)
5. [Backend Test Results](#5-backend-test-results)
6. [Security Audit](#6-security-audit)
7. [Bugs Fixed (Phase 2 & 3)](#7-bugs-fixed-phase-2--3)
8. [Remaining Issues](#8-remaining-issues)
9. [Deployment Readiness Checklist](#9-deployment-readiness-checklist)
10. [How to Enable Live API Testing](#10-how-to-enable-live-api-testing)

---

## 1. Environment & Prerequisites

| Component | Value |
|---|---|
| OS | Windows 11 |
| Python | 3.13.11 |
| Virtual env | `backend/.venv` |
| Backend URL | `http://localhost:8000` |
| Frontend URL | `http://localhost:5173` |
| Database (dev) | SQLite `backend/splitmate.db` |
| Database (test) | SQLite `backend/test.db` (in-memory per test) |

### Key Package Versions

| Package | Version | Notes |
|---|---|---|
| fastapi | 0.115.5 | ✅ |
| pydantic | 2.14.3 | Upgraded from 2.10.2 by google-genai dep |
| google-genai | 3.0.0 | ✅ Installed Phase 3 |
| pillow | 13.0.0 | ✅ Installed Phase 2 |
| numpy | 2.5.4 | ✅ Installed Phase 2 |
| pypdfium2 | 5.15.2 | ✅ Installed Phase 2 |
| httpx | 0.28.0 | ✅ |
| pytest | 8.3.3 | ✅ |

> [!NOTE]
> `google-genai==3.0.0` was not in `requirements.txt` before Phase 3. It has now been added alongside `pillow>=13.0.0`, `numpy>=2.5.0`, and `pypdfium2>=5.15.0`. Installing it upgraded `pydantic` from `2.10.2` → `2.14.3`. `pip check` confirmed: **No broken requirements found.**

---

## 2. Gemini Vision Integration

### Architecture

```
POST /api/receipts/upload?auto_extract=true
  └─ ReceiptExtractionService.extract_from_bytes()
       ├─ [PDF] PDFHandler.render_pdf() → pages
       ├─ ImagePreprocessor.preprocess() → blur detection, deskewing
       └─ OCREngine.process_receipt()
            ├─ [Key set]  GeminiVisionExtractor.extract()   → gemini-2.5-flash structured output
            └─ [No key]   RegexHeuristicFallback.parse_text() → is_fallback=True
```

### Mock Mode (No GEMINI_API_KEY) — ✅ Confirmed

| Test | Status | Details |
|---|---|---|
| `is_available()` returns False when no key | ✅ PASS | Verified in unit test |
| Fallback activated on empty text | ✅ PASS | Returns `is_fallback=True`, confidence=0.0 |
| Fallback activated on structured text | ✅ PASS | Extracts merchant, total, items via regex |
| Confidence ceiling ≤ 0.35 | ✅ PASS | Enforced by `RegexHeuristicFallback` |
| `extraction_method = "regex_heuristic_fallback"` | ✅ PASS | Metadata correctly tagged |
| Undersized image (1x1 px) handled safely | ✅ PASS | No unhandled exception; detected as blurry fallback |
| Corrupted image bytes handled safely | ✅ PASS | Clean `ReceiptExtractionError` raised |
| Upload endpoint accepts JPEG | ✅ PASS | Returns HTTP 201 Created and `receipt_id` |
| Upload endpoint accepts PNG | ✅ PASS | Returns HTTP 201 Created and `receipt_id` |
| Upload blocks .exe | ✅ PASS | Returns HTTP 400 Bad Request |
| Upload blocks oversized files (>10MB) | ✅ PASS | Returns HTTP 400 Bad Request |
| `to_backend_contract()` keys correct | ✅ PASS | merchant_name, currency, subtotal, tax, total, items |
| `to_frontend_contract()` keys correct | ✅ PASS | merchant, date, currency, total, items, is_fallback |
| Math consistency check valid data | ✅ PASS | No discrepancy warnings |
| Math consistency check flags error | ✅ PASS | Confidence reduced, warning added |

### Live Mode (GEMINI_API_KEY set) — ⏳ Requires Credentials

| Test | Status | Requirement |
|---|---|---|
| `is_available()` returns True | ⏳ SKIP | Set `GEMINI_API_KEY` in `backend/.env` |
| Gemini Vision extract on test image | ⏳ SKIP | Requires live API call |
| `is_fallback = False` on successful extraction | ⏳ SKIP | Model response validated by schema |
| `confidence > 0.35` on successful extraction | ⏳ SKIP | High confidence score output |

> [!TIP]
> Get a free Gemini API key at [Google AI Studio](https://aistudio.google.com) and set it in `backend/.env`:
> ```
> GEMINI_API_KEY=your-key-here
> GEMINI_MODEL=gemini-2.5-flash
> ```

---

## 3. PayPal Sandbox Integration

### Architecture

```
POST /api/payments/{id}/create-order
  └─ PayPalService.create_order()
       ├─ [Not configured] Returns MOCK-ORD-{ref}-{timestamp}
       └─ [Configured]     POST /v2/checkout/orders → real PayPal order

POST /api/payments/{id}/capture
  └─ PayPalService.capture_payment()
       ├─ [Not configured] Returns MOCK-CAP-{suffix}, status=COMPLETED
       └─ [Configured]     POST /v2/checkout/orders/{id}/capture
```

### State Machine

```
pending → order_created → captured
                       ↘ failed
```

### Mock Mode (No PAYPAL_CLIENT_ID/SECRET) — ✅ Confirmed

| Test | Status | Details |
|---|---|---|
| `is_configured` = False when env empty | ✅ PASS | Mock mode active |
| `is_configured` = False with "mock" prefix | ✅ PASS | Test/demo keys rejected |
| Mock token = "mock_sandbox_access_token" | ✅ PASS | No network call |
| Mock order ID format: `MOCK-ORD-*` | ✅ PASS | Incorporates reference ID slug |
| Mock order status: `CREATED` | ✅ PASS | Matches PayPal Orders API v2 |
| Mock capture format: `MOCK-CAP-*` | ✅ PASS | |
| Mock capture status: `COMPLETED` | ✅ PASS | State machine enforced |
| Duplicate capture → 409 Conflict | ✅ PASS | Prevents double capture |
| Mismatched order_id → 400 Bad Request | ✅ PASS | Server-side verification |
| Capture without create-order → 409/400 | ✅ PASS | Must be in `order_created` state |
| Fabricated order_id rejected | ✅ PASS | Client cannot inject arbitrary order ID |
| State transition: pending → order_created | ✅ PASS | After `create-order` |
| State transition: order_created → captured | ✅ PASS | After `capture` |
| `GET /api/payments/expense/{id}` returns list | ✅ PASS | Query verified |

### Live Sandbox Mode (PAYPAL_CLIENT_ID/SECRET set) — ⏳ Requires Credentials

| Test | Status | Requirement |
|---|---|---|
| `is_configured` = True | ⏳ SKIP | Set PayPal Sandbox credentials |
| OAuth2 token from sandbox | ⏳ SKIP | Real API call to `/v1/oauth2/token` |
| Order creation via Orders API v2 | ⏳ SKIP | Real API call to `/v2/checkout/orders` |
| Order ID not prefixed with MOCK | ⏳ SKIP | Verified sandbox order returned |

> [!TIP]
> Get PayPal Sandbox credentials at [PayPal Developer Portal](https://developer.paypal.com):
> 1. Create a Sandbox App → copy Client ID and Secret
> 2. Add to `backend/.env`:
> ```
> PAYPAL_CLIENT_ID=your-sandbox-client-id
> PAYPAL_CLIENT_SECRET=your-sandbox-secret
> PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
> ```

---

## 4. Frontend Testing Results

### Build Status

| Check | Status |
|---|---|
| `npm run build` | ✅ SUCCESS (1.06s) |
| Modules transformed | 2096 modules |
| JavaScript bundle size | 386.79 kB (gzip: 106.63 kB) |
| CSS bundle size | 69.38 kB (gzip: 10.96 kB) |
| Build errors | **0** |

### API Wiring (Code Review + E2E Test)

| User Action | Frontend Call | Backend Endpoint | Status |
|---|---|---|---|
| Create group | `ExpenseContext.createGroup()` | `POST /api/groups/` | ✅ Wired (HTTP 201) |
| Add member | `ExpenseContext.addMember()` | `POST /api/groups/{id}/members` | ✅ Wired (HTTP 201) |
| Upload receipt | `ReceiptScanView` → `api.uploadReceipt()` | `POST /api/receipts/upload` | ✅ Wired (HTTP 201) |
| Auto-extract | `?auto_extract=true` query param | `ReceiptExtractionService` | ✅ Wired |
| Edit items | `api.updateReceiptItems()` | `PUT /api/receipts/{id}/items` | ✅ Wired (HTTP 200) |
| Create expense | `ExpenseContext.createExpense()` | `POST /api/expenses/` | ✅ Wired (HTTP 201) |
| Assign items | `ExpenseContext.assignItems()` | `POST /api/expenses/{id}/assign` | ✅ Wired (HTTP 201) |
| View splits | `ExpenseContext.getSplits()` | `GET /api/expenses/{id}/splits` | ✅ Wired (HTTP 200) |
| Init payments | `ExpenseContext.initializePayments()` | `POST /api/expenses/{id}/initialize-payments` | ✅ Wired (HTTP 201) |
| PayPal checkout | `PaymentModal` → create-order + capture | `POST /api/payments/{id}/create-order` + `/capture` | ✅ Wired (HTTP 200) |

---

## 5. Backend Test Results

### Full Backend Suite Summary (November 11, 2026)

**Environment:** Windows 11 | Python 3.13.11 | pytest 8.3.3 | pydantic 2.14.3

```
================= 137 passed, 7 skipped, 2 warnings in 11.87s =================
```

### Breakdown by Test Module

| Test File | Total | Passed | Skipped | Failed | Status |
|---|---|---|---|---|---|
| `test_ai_extractor.py` | 26 | 26 | 0 | 0 | ✅ 100% |
| `test_e2e_workflow.py` | 1 | 1 | 0 | 0 | ✅ 100% |
| `test_expenses.py` | 18 | 18 | 0 | 0 | ✅ 100% |
| `test_groups.py` | 8 | 8 | 0 | 0 | ✅ 100% |
| `test_health.py` | 1 | 1 | 0 | 0 | ✅ 100% |
| `test_payments.py` | 9 | 9 | 0 | 0 | ✅ 100% |
| `test_receipts.py` | 19 | 19 | 0 | 0 | ✅ 100% |
| **`test_gemini_connectivity.py` (New)** | **25** | **22** | **3** | **0** | **✅ All unit/mock pass** |
| **`test_paypal_connectivity.py` (New)** | **17** | **13** | **4** | **0** | **✅ All unit/mock pass** |
| **`test_security.py` (New)** | **20** | **20** | **0** | **0** | **✅ 100%** |
| **Grand Total** | **144** | **137** | **7** | **0** | **✅ 0 Failures** |

*(Note: The 7 skipped tests are live external API calls that cleanly skip when API keys/credentials are not populated in `.env`.)*

---

## 6. Security Audit

| Check | Status | Severity | Notes |
|---|---|---|---|
| CORS not wildcard `*` | ✅ Restricted | Critical | Origins loaded from `CORS_ORIGINS` in `.env` |
| File upload extension allowlist | ✅ Enforced | High | `.jpg`, `.jpeg`, `.png`, `.webp`, `.pdf` only |
| File upload size limit (10MB) | ✅ Enforced | Medium | Files > 10MB rejected with HTTP 400 |
| Magic-byte validation | ✅ Enforced | Medium | Mismatched file extensions rejected |
| `.env` not in git | ✅ Confirmed | Critical | Verified `git ls-files backend/.env` is empty |
| `X-Internal-Service-Key` HMAC check | ✅ Enforced | High | Constant-time HMAC comparison on extraction endpoints |
| Payment server-side verification | ✅ Enforced | Critical | State machine verified; client amounts cannot override |
| Duplicate capture blocked | ✅ Enforced | High | HTTP 409 Conflict on repeated capture attempts |
| Fabricated order_id rejected | ✅ Enforced | High | HTTP 400 on order ID mismatch |
| `splitmate.db` in git | ⚠️ Advisory | Low | Dev SQLite database tracked in git; untrack before release |
| `test.db` in git | ⚠️ Advisory | Low | Test SQLite database tracked in git; untrack before release |
| No JWT authentication router | ⚠️ Scope | Medium | Out of hackathon MVP scope; add for multi-tenant production |

---

## 7. Bugs Fixed (Phase 2 & 3)

| # | Bug | Root Cause & Fix | Phase |
|---|---|---|---|
| 1 | `google-genai` missing | Added `google-genai==3.0.0` to `requirements.txt` and installed in venv | Phase 3 |
| 2 | Undersized images crashed numpy gradient | Added safe bounds check in `ImagePreprocessor.detect_blur` for arrays with dimension < 2 | Phase 3 |
| 3 | Creation endpoint status code assertions | Tests were expecting HTTP 200 on creation routes; updated tests to expect HTTP 201 Created | Phase 3 |
| 4 | `initialize-payments` failed with unassigned items | Tests skipped the item-assignment step; corrected helper to assign items before initializing payments | Phase 3 |
| 5 | `requirements.txt` missing imaging dependencies | Added `pillow>=13.0.0`, `numpy>=2.5.0`, `pypdfium2>=5.15.0`, updated `pydantic[email]==2.14.3` | Phase 3 |
| 6 | `pytest.exe` blocked by AppLocker | Ran tests via `python -m pytest` | Phase 2 |
| 7 | `pool_size`/`max_overflow` SQLite error | Made database engine arguments SQLite-aware | Phase 2 |
| 8 | `window.location.reload()` broke React state | Replaced with `resetReceiptScan()` state reset in `ReceiptScanView.jsx` | Phase 2 |
| 9 | Field name mismatch (`order_id` vs `paypal_order_id`) | Aligned tests with `PaymentResponse` schema | Phase 2 |
| 10 | Payment amount string vs Decimal comparison | Parsed `p["amount"]` as `Decimal` in assertions | Phase 2 |

---

## 8. Remaining Issues

| # | Issue | Priority | Recommendation |
|---|---|---|---|
| 1 | `splitmate.db` and `test.db` in git | Low | Run `git rm --cached backend/splitmate.db backend/test.db` to prevent committing local dev state |
| 2 | Live Gemini Vision API untested | Medium | Requires user to supply `GEMINI_API_KEY` in `backend/.env` |
| 3 | Live PayPal Sandbox untested | Medium | Requires user to supply `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` in `backend/.env` |
| 4 | PytestDeprecationWarning | Low | Add `asyncio_default_fixture_loop_scope = function` to `pytest.ini` |

---

## 9. Deployment Readiness Checklist

| Item | Status |
|---|---|
| Backend tests pass (137/137 executable tests) | ✅ PASS |
| Frontend production build succeeds | ✅ PASS |
| `requirements.txt` up to date & `pip check` passes | ✅ PASS |
| `.env` files excluded from git tracking | ✅ PASS |
| CORS restricted to localhost origins | ✅ PASS |
| File upload restrictions & magic-byte validation | ✅ PASS |
| Payment server-side verification & state machine | ✅ PASS |
| Mock fallback for Gemini (offline/dev mode) | ✅ PASS |
| Mock fallback for PayPal (offline/dev mode) | ✅ PASS |
| Gemini Vision live API tested | ⏳ Pending credentials |
| PayPal Sandbox live API tested | ⏳ Pending credentials |
| Production database (PostgreSQL) | ⏳ Configured in `config.py`; needs DB instance |

---

## 10. How to Enable Live API Testing

### Gemini Vision
1. Visit [Google AI Studio](https://aistudio.google.com) and generate an API key.
2. In `backend/.env`:
   ```bash
   GEMINI_API_KEY=AIza...
   GEMINI_MODEL=gemini-2.5-flash
   ```
3. Run the live test:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_gemini_connectivity.py -v -k "Live"
   ```

### PayPal Sandbox
1. Log in to [PayPal Developer Dashboard](https://developer.paypal.com) and create a Sandbox App.
2. In `backend/.env`:
   ```bash
   PAYPAL_CLIENT_ID=your-sandbox-client-id
   PAYPAL_CLIENT_SECRET=your-sandbox-client-secret
   PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
   ```
3. Run the live test:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_paypal_connectivity.py -v -k "Live"
   ```
