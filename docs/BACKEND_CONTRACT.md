# SplitMate Backend Contract & Team Integration Guide

**Version:** 0.1.0  
**Backend Lead:** Tanishq  
**Target Deadline:** November 13, 2026  
**Default Base URL:** `http://localhost:8000`

---

## Table of Contents

1. [Architecture & System Overview](#1-architecture--system-overview)
2. [For Pawan: AI Receipt Extraction Integration](#2-for-pawan-ai-receipt-extraction-integration)
3. [For Dhruv: Frontend API Contract & Integration](#3-for-dhruv-frontend-api-contract--integration)
4. [For Tanay: PayPal Integration Contract](#4-for-tanay-paypal-integration-contract)
5. [For Sunil: QA, Testing, Database & Deployment Guide](#5-for-sunil-qa-testing-database--deployment-guide)
6. [Security & Architectural Guardrails](#6-security--architectural-guardrails)

---

## 1. Architecture & System Overview

SplitMate uses:
- **Backend Framework:** FastAPI with Uvicorn
- **Database:** PostgreSQL (with SQLAlchemy 2.0 ORM & Alembic migrations)
- **Data Validation:** Pydantic v2
- **Authentication & Security:** JWT (HS256) with PyJWT, bcrypt password hashing, IDOR authorization guards, file magic-byte validation, and machine-to-machine internal service authentication.
- **Precision:** `Decimal` (`NUMERIC(12, 2)` / `NUMERIC(10, 4)`) for all financial amounts to eliminate floating-point rounding errors.
- **Identifiers:** Standard UUID v4 strings for all primary and foreign keys.

### High-Level Workflow:
```
[User] -> [Upload Receipt] -> [FastAPI backend: stores file & creates Receipt record (pending)]
                                     |
                                     v
                        [Pawan's AI Agent: extracts data]
                                     |
                                     v
[User reviews items in React UI] <- [POST /api/receipts/{receipt_id}/extraction]
         |
         v
[User creates Expense & assigns items to members] -> [POST /api/expenses/{id}/assign]
                                                             |
                                                             v
[Backend computes splits (Pure GET)] <------------ [GET /api/expenses/{id}/splits]
         |
         v
[User confirms split & initializes payments] ----> [POST /api/expenses/{id}/initialize-payments]
                                                             |
                                                             v
[Tanay's PayPal module creates order & captures] -> [POST /api/payments/{id}/create-order]
                                                 -> [POST /api/payments/{id}/capture]
```

---

## 2. For Pawan: AI Receipt Extraction Integration

Pawan is responsible for extracting merchant details, line items, quantities, taxes, and totals from uploaded receipt images/PDFs.

### Step 1: User Uploads Receipt
When a user uploads a receipt file (JPEG, PNG, WEBP, or PDF), the backend saves the file and generates a `receipt_id` with `extraction_status: "pending"`.

### Step 2: Extracting Information
Your AI worker reads the receipt image from storage or processes the file uploaded via `/api/receipts/upload`.

### Step 3: Submitting Extraction Results
Submit the extracted structured data via HTTP POST:

**Endpoint:** `POST /api/receipts/{receipt_id}/extraction`  
**Content-Type:** `application/json`

> [!IMPORTANT]
> **Authentication required (Fix 3 — Security):** This endpoint now requires a shared internal service secret.  
> You must include the following HTTP header in every request:
> ```
> X-Internal-Service-Key: <value of INTERNAL_SERVICE_SECRET>
> ```
> - The secret value is configured in the backend `.env` file under the key `INTERNAL_SERVICE_SECRET`.
> - Tanishq will share the actual secret value with you directly (never commit it to Git).
> - Requests missing this header receive **HTTP 401**. Requests with an incorrect value receive **HTTP 403**.
>
> **Python example using `requests`:**
> ```python
> import os, requests
>
> BACKEND_URL = os.getenv("SPLITMATE_BACKEND_URL", "http://localhost:8000")
> INTERNAL_KEY = os.getenv("INTERNAL_SERVICE_SECRET")  # load from your own .env
>
> response = requests.post(
>     f"{BACKEND_URL}/api/receipts/{receipt_id}/extraction",
>     headers={"X-Internal-Service-Key": INTERNAL_KEY},
>     json=extraction_payload,
> )
> ```

#### Request Payload Specification:
```json
{
  "merchant_name": "Mario's Italian Bistro",
  "currency": "USD",
  "subtotal": 54.50,
  "tax": 4.90,
  "total": 59.40,
  "items": [
    {
      "item_name": "Margherita Pizza Large",
      "quantity": 1,
      "unit_price": 22.00,
      "total_price": 22.00
    },
    {
      "item_name": "Fettuccine Alfredo",
      "quantity": 2,
      "unit_price": 14.00,
      "total_price": 28.00
    },
    {
      "item_name": "San Pellegrino Sparkling Water",
      "quantity": 1,
      "unit_price": 4.50,
      "total_price": 4.50
    }
  ]
}
```

#### Field Specifications & Validation Rules:
| Field | Type | Required | Description / Rules |
|---|---|---|---|
| `merchant_name` | `string` | Yes | 1 to 255 characters. The identified vendor / restaurant. |
| `currency` | `string` | Yes | 3-letter ISO currency code (e.g., `"USD"`, `"EUR"`, `"GBP"`). Defaults to `"USD"`. |
| `subtotal` | `number` / `string` | Yes | Non-negative decimal with up to 2 decimal places. |
| `tax` | `number` / `string` | Yes | Non-negative decimal with up to 2 decimal places. |
| `total` | `number` / `string` | Yes | Non-negative decimal with up to 2 decimal places. Should equal subtotal + tax (+ tip if applicable). |
| `items` | `array` | Yes | Non-empty list of item objects. |
| `items[].item_name` | `string` | Yes | Name / description of line item (1 to 255 characters). |
| `items[].quantity` | `integer` | Yes | Minimum 1. |
| `items[].unit_price` | `number` / `string` | Yes | Non-negative decimal, up to 2 decimal places. |
| `items[].total_price` | `number` / `string` | Yes | Non-negative decimal (`quantity * unit_price`). |

#### Expected Response (`200 OK`):
Returns the complete `ReceiptResponse` with `extraction_status: "completed"` and all stored `ReceiptItem` IDs populated.

#### Error Handling:
- `401 Unauthorized`: Missing `X-Internal-Service-Key` header.
- `403 Forbidden`: Incorrect `X-Internal-Service-Key` value.
- `404 Not Found`: If `receipt_id` does not exist.
- `409 Conflict`: If extraction results have already been submitted for this receipt.
- `422 Unprocessable Entity`: Validation failure (e.g. missing fields or invalid format).

---

## 3. For Dhruv: Frontend API Contract & Integration

Dhruv owns the React + TypeScript + Vite frontend.

### General Configuration
- **API Base URL:** `http://localhost:8000` (Configure as `VITE_API_BASE_URL` in frontend `.env`)
- **CORS Allowed Origins:** Default includes `http://localhost:5173` (Vite) and `http://localhost:3000`. Configurable via `CORS_ORIGINS` in backend `.env`.
- **Response Format:** All JSON responses return camel/snake case as documented below.
- **Error Format:** Standard FastAPI error format:
  ```json
  {
    "detail": "Descriptive error message"
  }
  ```
  Validation errors (`422`) return:
  ```json
  {
    "detail": [
      {
        "loc": ["body", "name"],
        "msg": "field required",
        "type": "value_error.missing"
      }
    ]
  }
  ```

---

### Endpoint Reference

#### 1. System Health (Public)
- **`GET /health`**
  - **Auth:** None (Public)
  - **Response (`200 OK`):**
    ```json
    {
      "status": "ok",
      "version": "0.1.0"
    }
    ```

---

#### 2. Authentication (Public & User Endpoints)

##### `POST /api/auth/register`
- **Auth:** None (Public)
- **Description:** Registers a new user. Passwords must be at least 8 characters.
- **Request Body:**
  ```json
  {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "password": "StrongPassword123!"
  }
  ```
- **Response (`201 Created`):**
  ```json
  {
    "id": "e4b52c6f-612b-426b-8cf7-cb7dfc64c782",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "created_at": "2026-11-10T12:00:00Z"
  }
  ```
- **Error Responses:**
  - `400 Bad Request`: Email already registered.
  - `422 Unprocessable Entity`: Invalid email format or password less than 8 characters.

##### `POST /api/auth/login`
- **Auth:** None (Public)
- **Description:** Authenticates user credentials and issues a signed JWT access token.
- **Request Body:**
  ```json
  {
    "email": "jane@example.com",
    "password": "StrongPassword123!"
  }
  ```
- **Response (`200 OK`):**
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "user": {
      "id": "e4b52c6f-612b-426b-8cf7-cb7dfc64c782",
      "name": "Jane Doe",
      "email": "jane@example.com",
      "created_at": "2026-11-10T12:00:00Z"
    }
  }
  ```
- **Error Responses:**
  - `401 Unauthorized`: Invalid email or password.

##### `GET /api/auth/me`
- **Auth:** `Authorization: Bearer <access_token>`
- **Description:** Returns the authenticated user's profile.
- **Response (`200 OK`):**
  ```json
  {
    "id": "e4b52c6f-612b-426b-8cf7-cb7dfc64c782",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "created_at": "2026-11-10T12:00:00Z"
  }
  ```
- **Error Responses:**
  - `401 Unauthorized`: Missing, expired, or invalid token.

---

> [!IMPORTANT]
> **Authentication for Protected Endpoints:**
> All endpoints under `/api/groups`, `/api/receipts` (upload & get), `/api/expenses`, and `/api/payments` require the user's JWT access token in the request header:
> ```http
> Authorization: Bearer <access_token>
> ```
> Requests without this header receive **HTTP 401 Unauthorized**.
> The only exceptions are:
> 1. `GET /health` (Public)
> 2. `POST /api/auth/register` (Public)
> 3. `POST /api/auth/login` (Public)
> 4. `POST /api/receipts/{receipt_id}/extraction` (Requires machine-to-machine `X-Internal-Service-Key`, NOT user JWT)

---

#### 3. Receipts (Protected)

##### `POST /api/receipts/extract` (Asynchronous AI Extraction Flow)
- **Auth:** `Authorization: Bearer <access_token>`
- **Content-Type:** `multipart/form-data`
- **Form Data:** `file`: Binary receipt image or PDF (Accepted: `.jpg`, `.jpeg`, `.png`, `.webp`, `.pdf`. Max size: 10 MB).
- **Behavior:**
  1. Validates magic bytes and stores file.
  2. Creates `Receipt` record with status `pending`.
  3. Commits transaction and schedules `process_receipt_extraction_task` via FastAPI `BackgroundTasks`.
  4. Returns `HTTP 202 Accepted` immediately.
- **Response (`202 Accepted`):**
  ```json
  {
    "receipt_id": "e4b52c6f-612b-426b-8cf7-cb7dfc64c782",
    "extraction_status": "pending"
  }
  ```

##### `GET /api/receipts/{receipt_id}`
- **Auth:** `Authorization: Bearer <access_token>` (Uploader or Group Member)
- **Response (`200 OK`):**
  ```json
  {
    "receipt_id": "e4b52c6f-612b-426b-8cf7-cb7dfc64c782",
    "original_filename": "dinner_bill.jpg",
    "merchant_name": "Mario's Italian Bistro",
    "currency": "USD",
    "subtotal": 54.50,
    "tax": 4.90,
    "total": 59.40,
    "extraction_status": "completed",
    "missing_fields": null,
    "uncertain_fields": null,
    "warnings": null,
    "confidence": 0.95,
    "error_code": null,
    "error_message": null,
    "is_user_reviewed": false,
    "created_at": "2026-11-07T17:15:00.000000Z",
    "items": [
      {
        "id": "8a32a0c4-110a-48d6-95f0-6c9c6fbb3e60",
        "receipt_id": "e4b52c6f-612b-426b-8cf7-cb7dfc64c782",
        "item_name": "Margherita Pizza Large",
        "quantity": "1.0000",
        "unit_price": 22.00,
        "total_price": 22.00
      }
    ]
  }
  ```

##### `PUT /api/receipts/{receipt_id}/review` (Human Review for `review_required`)
- **Auth:** `Authorization: Bearer <access_token>` (Uploader or Group Member)
- **Precondition:** `extraction_status` must be `"review_required"`. Otherwise returns `409 Conflict`.
- **Request Body:**
  ```json
  {
    "merchant_name": "Mario's Italian Bistro",
    "currency": "USD",
    "subtotal": 45.50,
    "tax": 3.64,
    "total": 49.14,
    "items": [
      {
        "item_name": "Margherita Pizza",
        "quantity": "2.0000",
        "unit_price": 12.00,
        "total_price": 24.00
      },
      {
        "item_name": "Garlic Bread",
        "quantity": "1.0000",
        "unit_price": 21.50,
        "total_price": 21.50
      }
    ]
  }
  ```
- **Validation Rules:**
  - `currency`: Valid 3-letter ISO code.
  - `total`: Must be strictly positive.
  - `items`: At least 1 item with positive quantity and non-negative prices.
  - Item math: `quantity × unit_price` must equal `total_price` exactly (server-side exact decimal check).
  - Financial reconciliation: **not enforced server-side** during human review. A receipt may legitimately contain uncaptured adjustments (tip, discount, service charge, delivery fee) that cause `subtotal + tax ≠ total`.
- **Response (`200 OK`):** Updated `ReceiptResponse` with `extraction_status: "completed"` and `is_user_reviewed: true`.

##### `POST /api/receipts/upload` (Direct Synchronous Storage)
- **Content-Type:** `multipart/form-data`
- **Form Data:** `file`: Binary file (Accepted: `.jpg`, `.jpeg`, `.png`, `.webp`, `.pdf`. Max size: 10 MB).
- **Response (`201 Created`):** `ReceiptResponse` with `extraction_status: "pending"`.

---

#### 3. Expense Groups & Members
- **`POST /api/groups`**
  - **Body:**
    ```json
    {
      "name": "Friday Night Italian Dinner"
    }
    ```
  - **Response (`201 Created`):**
    ```json
    {
      "id": "18f9da94-43ea-44fb-81ff-ef728bbad315",
      "name": "Friday Night Italian Dinner",
      "created_at": "2026-11-07T17:15:00.000000Z"
    }
    ```

- **`GET /api/groups/{group_id}`**
  - **Response (`200 OK`):** Same schema as `POST /api/groups`.

- **`POST /api/groups/{group_id}/members`**
  - **Body:**
    ```json
    {
      "name": "Dhruv",
      "email": "dhruv@example.com"
    }
    ```
  - **Response (`201 Created`):**
    ```json
    {
      "id": "3bf54bb5-3dc0-4581-9b65-ea933b9c7b64",
      "group_id": "18f9da94-43ea-44fb-81ff-ef728bbad315",
      "name": "Dhruv",
      "email": "dhruv@example.com",
      "created_at": "2026-11-07T17:15:00.000000Z"
    }
    ```

- **`GET /api/groups/{group_id}/members`**
  - **Response (`200 OK`):** Array of member objects.

---

#### 4. Expenses & Item Assignments
- **`POST /api/expenses`**
  - **Body:**
    ```json
    {
      "group_id": "18f9da94-43ea-44fb-81ff-ef728bbad315",
      "receipt_id": "e4b52c6f-612b-426b-8cf7-cb7dfc64c782",
      "total_amount": 59.40,
      "currency": "USD"
    }
    ```
  - **Response (`201 Created`):**
    ```json
    {
      "id": "673f8a0a-bf19-4cb5-8278-f71694b7dc6a",
      "group_id": "18f9da94-43ea-44fb-81ff-ef728bbad315",
      "receipt_id": "e4b52c6f-612b-426b-8cf7-cb7dfc64c782",
      "total_amount": 59.40,
      "currency": "USD",
      "created_at": "2026-11-07T17:15:00.000000Z"
    }
    ```

- **`POST /api/expenses/{expense_id}/assign`**
  - Assigns receipt items to members. Supports split shares (e.g. 2 members sharing an item each set `share_quantity: 0.5`).
  - **Body:**
    ```json
    {
      "assignments": [
        {
          "receipt_item_id": "8a32a0c4-110a-48d6-95f0-6c9c6fbb3e60",
          "member_id": "3bf54bb5-3dc0-4581-9b65-ea933b9c7b64",
          "share_quantity": 0.5
        },
        {
          "receipt_item_id": "8a32a0c4-110a-48d6-95f0-6c9c6fbb3e60",
          "member_id": "5dc43cc1-7892-482a-a92c-15a9f658f331",
          "share_quantity": 0.5
        }
      ]
    }
    ```
  - **Response (`201 Created`):** Array of created assignment records.

- **`GET /api/expenses/{expense_id}/splits`**
  - **Idempotent & Read-Only:** Computes each member's item subtotal, distributed tax/fees, and reconciled total share. Does NOT mutate or create any database records.
  - **Penny Allocation Guarantee:** Sum of member `amount` fields is mathematically guaranteed to equal `expense.total_amount` down to the exact cent.
  - **Response (`200 OK`):**
    ```json
    {
      "expense_id": "673f8a0a-bf19-4cb5-8278-f71694b7dc6a",
      "total_amount": 59.40,
      "currency": "USD",
      "splits": [
        {
          "member_id": "3bf54bb5-3dc0-4581-9b65-ea933b9c7b64",
          "member_name": "Dhruv",
          "member_email": "dhruv@example.com",
          "allocated_subtotal": 27.25,
          "allocated_tax": 2.45,
          "amount": 29.70,
          "currency": "USD"
        },
        {
          "member_id": "5dc43cc1-7892-482a-a92c-15a9f658f331",
          "member_name": "Tanishq",
          "member_email": "tanishq@example.com",
          "allocated_subtotal": 27.25,
          "allocated_tax": 2.45,
          "amount": 29.70,
          "currency": "USD"
        }
      ]
    }
    ```

- **`POST /api/expenses/{expense_id}/initialize-payments`**
  - **Side-effectful:** Converts calculated splits into pending `Payment` records for each member in the split.
  - **Idempotency & Safety:** Safely updates existing `pending` payments if shares were re-calculated. Returns `409 Conflict` if any payment is already in `order_created` or `captured` state.
  - **Response (`201 Created`):** Array of initialized `PaymentResponse` records:
    ```json
    [
      {
        "id": "e93817f2-1a48-4cb2-850d-b4b1a4157121",
        "expense_id": "673f8a0a-bf19-4cb5-8278-f71694b7dc6a",
        "member_id": "3bf54bb5-3dc0-4581-9b65-ea933b9c7b64",
        "amount": 29.70,
        "currency": "USD",
        "paypal_order_id": null,
        "paypal_capture_id": null,
        "status": "pending",
        "created_at": "2026-11-07T17:15:00.000000Z",
        "updated_at": "2026-11-07T17:15:00.000000Z"
      }
    ]
    ```

---

#### 5. Payments
- **`GET /api/payments/{payment_id}`**
  - **Response (`200 OK`):**
    ```json
    {
      "id": "e93817f2-1a48-4cb2-850d-b4b1a4157121",
      "expense_id": "673f8a0a-bf19-4cb5-8278-f71694b7dc6a",
      "member_id": "3bf54bb5-3dc0-4581-9b65-ea933b9c7b64",
      "amount": 29.70,
      "currency": "USD",
      "paypal_order_id": null,
      "paypal_capture_id": null,
      "status": "pending",
      "created_at": "2026-11-07T17:15:00.000000Z",
      "updated_at": "2026-11-07T17:15:00.000000Z"
    }
    ```

---

## 4. For Tanay: PayPal Integration Contract

Tanay owns the PayPal Sandbox client integration and server-side capture verification.

### Database Payment Model
Table: `payments`
- `id` (UUID): Primary key.
- `expense_id` (UUID): Expense foreign key.
- `member_id` (UUID): Group member foreign key.
- `amount` (NUMERIC(12, 2)): Exact payment amount.
- `currency` (VARCHAR(3)): Payment currency (default `"USD"`).
- `paypal_order_id` (VARCHAR(50)): Unique PayPal order ID.
- `paypal_capture_id` (VARCHAR(50)): PayPal capture reference.
- `status` (`payment_status_enum`): Enum:
  - `"pending"`: Split computed, awaiting PayPal order creation.
  - `"order_created"`: PayPal order generated via PayPal Orders API v2.
  - `"captured"`: Verified and captured via PayPal Capture API.
  - `"failed"`: Payment capture rejected or failed.

### Environment Configuration
The backend loads configuration in `app/core/config.py`. Tanay should configure:
```env
PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_sandbox_client_secret
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
```

### Endpoints for Tanay to Implement:

#### 1. Create PayPal Order
- **Endpoint:** `POST /api/payments/{payment_id}/create-order`
- **Location:** `app/api/routes/payments.py -> create_paypal_order`
- **Current State:** Implemented via `app/services/paypal_service.py` (PayPal Orders API v2 with token caching, pessimistic row locking, and idempotency key support).
- **Implementation Requirements:**
  1. Verify `payment.status == PaymentStatus.PENDING` (or existing order returned idempotently).
  2. Request an OAuth2 access token from PayPal Sandbox (`POST /v1/oauth2/token`).
  3. Call PayPal Orders API (`POST /v2/checkout/orders`):
     - `intent`: `"CAPTURE"`
     - `purchase_units`: `[{ amount: { currency_code: payment.currency, value: str(payment.amount) } }]`
  4. Save returned PayPal order ID: `payment.paypal_order_id = response.id`.
  5. Update status: `payment.status = PaymentStatus.ORDER_CREATED`.
  6. Commit transaction and return `PaymentResponse` including `approval_url`.

#### 2. Capture PayPal Payment
- **Endpoint:** `POST /api/payments/{payment_id}/capture`
- **Location:** `app/api/routes/payments.py -> capture_payment`
- **Current State:** Implemented via `app/services/paypal_service.py` (server-side capture verification, amount/currency validation, idempotent capture retry handling).
- **Body:**
  ```json
  {
    "paypal_order_id": "5O190127TN364715T"
  }
  ```
- **Implementation Requirements:**
  1. Verify `payment.status == PaymentStatus.ORDER_CREATED` (or return already captured payment idempotently).
  2. Reject if `payment.status == PaymentStatus.CAPTURED` when an unexpected capture request is received.
  3. Validate `body.paypal_order_id == payment.paypal_order_id`.
  4. Call PayPal Capture endpoint (`POST /v2/checkout/orders/{order_id}/capture`).
  5. **Server-Side Verification Requirement:** Never trust frontend confirmation. Inspect PayPal API response to confirm status is `"COMPLETED"`, and verify captured amount and currency match database payment record.
  6. Save `payment.paypal_capture_id = capture_id`.
  7. Set `payment.status = PaymentStatus.CAPTURED`.
  8. If PayPal rejects the capture, set `payment.status = PaymentStatus.FAILED`.

---

## 5. For Sunil: QA, Testing, Database & Deployment Guide

Sunil owns testing, integration verification, documentation, and the demo script.

### Backend Setup Instructions

#### 1. Prerequisites
- Python 3.12+
- PostgreSQL 14+ (or Docker running PostgreSQL)
- Git

#### 2. Environment Initialization
```powershell
# Navigate to backend directory
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### 3. Environment Variables
Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```
Update `DATABASE_URL` with your PostgreSQL credentials:
```
DATABASE_URL=postgresql://splitmate_user:splitmate_password@localhost:5432/splitmate_db
```

#### 4. PostgreSQL Database Setup
```sql
CREATE DATABASE splitmate_db;
CREATE USER splitmate_user WITH ENCRYPTED PASSWORD 'splitmate_password';
GRANT ALL PRIVILEGES ON DATABASE splitmate_db TO splitmate_user;
```

#### 5. Database Migrations
Run Alembic migrations to build the schema:
```powershell
alembic upgrade head
```
To check current migration revision:
```powershell
alembic current
```

#### 6. Starting the Server
```powershell
uvicorn app.main:app --reload --port 8000
```
Interactive API documentation:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

#### 7. Running the Automated Test Suite
```powershell
pytest tests/ -v
```
All 188 unit, integration, security, extraction, and PayPal tests use SQLite in-memory fixtures and run cleanly without requiring an external PostgreSQL instance.

---

### Integration Test Scenarios for QA Demo

1. **Scenario 1: User Registration & Authentication**
   - Register user via `POST /api/auth/register`.
   - Log in via `POST /api/auth/login` to obtain JWT Bearer access token.
   - Access `GET /api/auth/me` with Bearer token to verify current user identity.

2. **Scenario 2: Receipt Upload & AI Extraction Ingestion**
   - Upload receipt image via `POST /api/receipts/upload` with Bearer token.
   - Submit extraction payload via `POST /api/receipts/{id}/extraction` with `X-Internal-Service-Key` header.
   - Verify `GET /api/receipts/{id}` returns correct line items and `extraction_status: completed`.

3. **Scenario 3: Expense Creation & Member Assignment**
   - Create group via `POST /api/groups`.
   - Add 3 members via `POST /api/groups/{id}/members`.
   - Create expense for the group matching receipt total.
   - Batch assign items: Assign item 1 to member A (100%), item 2 shared equally between member B and C (50% each).

4. **Scenario 4: Split Calculation, Tax Distribution & Reconciliation**
   - Call `GET /api/expenses/{id}/splits`.
   - Verify pure read-only behavior (no payment records created).
   - Verify sum of splits matches `expense.total_amount` exactly down to the cent, including tax/tip.

5. **Scenario 5: Payment Initialization & IDOR Enforcement**
   - Call `POST /api/expenses/{id}/initialize-payments`.
   - Verify pending payment records are generated with exact matching amounts.
   - Verify a user can only create a PayPal order for their OWN share (`403 Forbidden` if attempting to pay someone else's share).
   - Verify calling initialize-payments again safely updates pending amounts.
   - Verify once any payment transitions to `order_created` or `captured`, re-initialization is blocked (`409 Conflict`).

6. **Scenario 6: Security & Validation Edge Cases**
   - Attempt accessing another user's group or receipt without membership -> Expect `404 Not Found` (IDOR concealment).
   - Attempt uploading non-supported file extension (`.exe` or `.txt`) or file with mismatched magic bytes -> Expect `400 Bad Request`.
   - Attempt submitting extraction without internal service key -> Expect `401 Unauthorized` (`403 Forbidden` if wrong key).
   - Attempt creating expense with total mismatching extracted receipt total -> Expect `400 Bad Request`.
   - Attempt initializing payments with unassigned receipt items -> Expect `400 Bad Request`.
   - Attempt assigning an item to a member outside the expense group -> Expect `400 Bad Request`.
   - Attempt assigning an item from a different receipt -> Expect `400 Bad Request`.
   - Attempt assigning more quantity than purchased (`> item.quantity`) -> Expect `400 Bad Request`.
   - Attempt creating order for non-pending payment -> Expect `409 Conflict`.

---

## 6. Security & Architectural Guardrails

1. **Authentication & Token Lifecycle:** Users authenticate via `POST /api/auth/login` to obtain an HMAC-SHA256 (HS256) JWT access token with a configurable expiration window (`ACCESS_TOKEN_EXPIRE_MINUTES`). Passwords are salted and hashed using `bcrypt` (12 rounds) and are never stored or returned.
2. **Multi-Tenant IDOR Isolation:** Group creators and explicit group members are the only principals authorized to view or mutate group resources (receipts, expenses, assignments, and payments). Unauthorized access attempts to cross-tenant resources return `404 Not Found` rather than `403 Forbidden` to prevent object existence enumeration.
3. **Payer-Specific Enforcement:** Users can only initiate or capture payments assigned directly to their own membership record; attempting to initiate payment for another member returns `403 Forbidden`.
4. **Machine-to-Machine Secret Isolation:** AI extraction ingestion via `POST /api/receipts/{receipt_id}/extraction` uses a dedicated `X-Internal-Service-Key` header verified with constant-time string comparison (`secrets.compare_digest`), decoupled from end-user JWT authentication.
5. **Zero Secret Leakage:** No API secrets, credentials, or `.env` files are checked into version control.
6. **Safe File Handling & Magic Bytes:** Uploaded filenames are sanitized and stored using random UUIDs (`uuid.uuid4().hex + ext`). File extensions, sizes, and file magic bytes (JPEG, PNG, WEBP, PDF signatures) are verified before disk writes. Internal absolute file paths are never returned to clients.
7. **Financial Precision:** All amounts are parsed and manipulated using Python's `Decimal` with `ROUND_HALF_UP` to prevent floating-point discrepancies.
8. **Penny Allocation:** Remainder residue is distributed to members with highest fractional discrepancy so that the sum of splits equals `total_amount` exactly.
9. **State Machine Integrity:** Payment status transitions are strictly unidirectional (`pending` -> `order_created` -> `captured` / `failed`). Duplicate captures and duplicate order creation are rejected.
10. **Receipt-Item Assignment Completeness:** Expense payment initialization strictly requires that every item from the associated receipt has been 100% assigned, preventing unassigned line items from being forgotten.
11. **Database Consistency:** Database foreign keys enforce `CASCADE` on groups/receipts/members and `SET NULL` on optional references to maintain relational integrity.

