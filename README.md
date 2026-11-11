# SplitMate 🚀
**AI-Powered Group Expense Splitting & PayPal Sandbox Settlement**  
*PayPal AI Hackathon 2026*

SplitMate is an intelligent group expense management platform that parses receipt images using AI vision OCR, computes mathematically accurate pro-rata bill splits (with penny reconciliation), and enables peer-to-peer debt settlements through the PayPal Orders API v2.

---

## 👥 Hackathon Team & Responsibilities

- **Tanishq**: FastAPI Backend Architecture, JWT Authentication, Group & Expense Ledger, and Role-Based Authorization.
- **Pawan**: AI Receipt Extraction Service (Computer vision OCR, itemization, and tax/tip parsing).
- **Dhruv**: React 19 Frontend Development, UI/UX Design, and Financial Dashboard.
- **Tanay**: PayPal Sandbox Integration (Orders API v2, Server-Side Capture, Row Locking, and Idempotency).
- **Sunil**: End-to-End Integration, Automated QA Suites, Security Audits, and Verification.

---

## 🏗 System Architecture

```text
SplitMate/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py              # Auth & database session dependencies
│   │   │   └── routes/              # Auth, Expenses, Groups, Receipts, Payments
│   │   ├── core/                    # Config (Pydantic Settings), Security (JWT/bcrypt)
│   │   ├── models/                  # SQLAlchemy ORM models (Users, Expenses, Payments)
│   │   ├── schemas/                 # Pydantic v2 validation contracts
│   │   └── services/                # PayPal Orders v2 service, Split Calculator
│   ├── migrations/                  # Alembic database migration versions
│   ├── tests/                       # Pytest test suite (118 test cases)
│   └── requirements.txt             # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── api/                     # Unified API client & endpoint contracts
│   │   ├── components/              # Fintech modals, PayPal buttons, expense tables
│   │   ├── context/                 # AuthContext (JWT), ExpenseContext, ThemeContext
│   │   └── views/                   # Dashboard, Scanner, Ledger, Analytics, Settings
│   └── package.json                 # React 19, Vite 8, @paypal/react-paypal-js
└── docs/                            # API contracts and security verification reports
```

---

## 💻 Windows Setup & Quick Start Guide

### Prerequisites
- **Python**: 3.11+ or 3.12+ (64-bit)
- **Node.js**: v18+ or v20+ LTS (Tested on `v26.13.0` & `npm 11.20.0`)
- **Git**

---

### Step 1: Backend Setup (FastAPI)

1. Open PowerShell and navigate to the backend directory:
   ```powershell
   cd backend
   ```

2. Create and activate a Python virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install required Python packages:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Configure environment variables:
   Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
   *Edit `.env` as needed:*
   ```env
   # Database: Use SQLite for zero-config local development
   DATABASE_URL=sqlite:///./splitmate.db

   # Application & CORS
   APP_ENV=development
   DEBUG=true
   CORS_ORIGINS=http://localhost:5173,http://localhost:3000

   # Security
   INTERNAL_SERVICE_SECRET=CHANGE_ME_GENERATE_STRONG_RANDOM_SECRET
   JWT_SECRET_KEY=CHANGE_ME_GENERATE_STRONG_SECRET_FOR_JWT

   # PayPal Sandbox Credentials (Obtain from developer.paypal.com)
   PAYPAL_CLIENT_ID=CHANGE_ME_PAYPAL_SANDBOX_CLIENT_ID
   PAYPAL_CLIENT_SECRET=CHANGE_ME_PAYPAL_SANDBOX_CLIENT_SECRET
   PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
   PAYPAL_TIMEOUT_SECONDS=10
   ```

5. Initialize the development database:
   ```powershell
   python -c "from app.db.session import engine, Base; import app.models.models; Base.metadata.create_all(bind=engine); print('Database initialized.')"
   ```

6. Start the FastAPI backend server:
   ```powershell
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```
   *The API will be available at `http://127.0.0.1:8000` with interactive Swagger docs at `http://127.0.0.1:8000/docs`.*

---

### Step 2: Frontend Setup (React + Vite)

1. Open a new PowerShell terminal and navigate to `frontend`:
   ```powershell
   cd frontend
   ```

2. Configure frontend environment variables:
   Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
   *Edit `frontend/.env`:*
   ```env
   VITE_API_BASE_URL=http://localhost:8000/api
   VITE_USE_MOCK_API=false
   VITE_PAYPAL_CLIENT_ID=CHANGE_ME_PAYPAL_SANDBOX_CLIENT_ID
   ```
   *(Note: Set `VITE_PAYPAL_CLIENT_ID` to your Sandbox Client ID matching backend `PAYPAL_CLIENT_ID`, or `'sb'` for sandbox testing).*

3. Install npm dependencies:
   ```powershell
   npm install
   ```

4. Start the Vite development server:
   ```powershell
   npm run dev
   ```
   *The frontend application will be live at `http://localhost:5173`.*

---

## 🧪 Running Automated Test Suites

### 1. Backend Regression Suite (Pytest)
From `backend/` with the virtual environment activated:
```powershell
pytest -v
```
- **117 passed, 1 skipped** (118 total test cases).
- Covers authentication, group authorization, receipt validation, expense calculations, PayPal OAuth, order creation, server-side capture, timeout reconciliation, and duplicate capture prevention.

### 2. Frontend Linting & Production Build
From `frontend/`:
```powershell
# Lint check with oxlint (0 errors)
npm run lint

# Production Vite bundle compilation
npm run build
```

---

## 💳 PayPal Sandbox Integration Flow

1. **Authentication:** User logs in via JWT Bearer authentication. Identity is cryptographically tied to all payment actions.
2. **Expense & Splits:** Expenses are created and itemized; backend computes exact member shares down to the cent.
3. **Payment Initialization:** `POST /api/expenses/{id}/initialize-payments` generates server-side pending payment records with authoritative amounts.
4. **Order Creation:** `@paypal/react-paypal-js` triggers `POST /api/payments/{id}/create-order`. The backend contacts PayPal Orders v2 with an idempotency key and row-level locking.
5. **Buyer Approval:** The buyer reviews and approves the transaction via the official PayPal Sandbox popup.
6. **Server-Side Capture:** Upon approval, frontend invokes `POST /api/payments/{id}/capture`. The backend verifies caller identity (`require_payer=True`), captures the order via PayPal Orders API v2, verifies captured amount and currency against database records, and marks status `CAPTURED`.
7. **Ledger Refresh:** Frontend automatically queries `GET /api/payments/history` and displays the confirmed PayPal Capture ID with celebratory confetti.

---

## ⚠️ Important Deployment & Architecture Notes

- **PayPal Sandbox Credentials**: A genuine PayPal payment execution requires real developer sandbox credentials in `.env`. Do **not** commit credentials to Git.
- **Database Architecture**: SQLite is used for local development and automated testing fixtures. PostgreSQL is the target production database architecture. Live PostgreSQL concurrency testing (`test_live_postgres_concurrent_capture_lock`) requires a running PostgreSQL instance and is automatically skipped when running SQLite.
