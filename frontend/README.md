# SplitMate — Frontend Application
**PayPal AI Hackathon 2026**

Built by **Dhruv Patil** (React Frontend & UI/UX Lead)

SplitMate is an AI-powered group expense management platform that extracts receipt details using AI vision OCR, simplifies expense splitting among teammates, and enables seamless peer-to-peer settlements through PayPal Sandbox.

---

## 🚀 Quick Start

```bash
# Navigate to the frontend directory
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

The app will be accessible at `http://localhost:3000`.

---

## 🌟 Key Features & Implemented Modules

1. **Authentication & Team Persona Switcher**:
   - Quick-switch between all 5 hackathon teammates (**Dhruv**, **Tanishq**, **Pawan**, **Tanay**, **Sunil**) to test different views, balances, and permissions.
   - Persistent user profile and connected PayPal Sandbox email.

2. **Main Dashboard**:
   - Live financial metric cards (*Net Balance*, *Owed to You*, *You Owe*, *Active Squads*).
   - Real-time backend connectivity pill (*FastAPI Live* vs *Demo Resilient Fallback*).
   - Instant PayPal Settle Up center.
   - Recent activity ledger with category iconography.

3. **AI Receipt Extraction (Pawan's Integration)**:
   - Drag-and-drop receipt image upload (supports JPG, PNG, WebP).
   - Interactive progress bar with scanning stages (*Uploading* -> *AI OCR Bounding Box Detection* -> *Line Item Parsing* -> *Total Computation*).
   - 3 pre-loaded one-click test receipts for hackathon demos:
     - **The Italian Bistro Trattoria** ($142.50)
     - **Whole Foods Market** ($88.45)
     - **Blue Bottle Coffee & Bakery** ($24.80)
   - Interactive item assignment: click member pills to assign dishes or tap *"Everyone"* for shared appetizers.
   - Pro-rated tax and tip calculations based on individual item consumption.

4. **PayPal Sandbox Integration (Tanay's Integration)**:
   - Dedicated PayPal settlement modal with authentic fintech styling.
   - PayPal Sandbox authentication and order lifecycle: `CREATED` -> `AUTHORIZING` -> `CAPTURING` -> `COMPLETED`.
   - Idempotency & duplicate submission prevention.
   - Generates and displays official PayPal Capture IDs (e.g. `CAPTURE-XXXXXXXXXX`).
   - Celebratory confetti effects upon successful settlement.

5. **Expense & Squad Management (Tanishq's Integration)**:
   - Create squads, manage members, and track group spending.
   - Add manual expenses with equal or exact splits.
   - Detailed itemized expense inspection modal with settlement shortcut.

6. **Transaction History & Export**:
   - Searchable, filterable ledger of all squad bills.
   - 1-click CSV report export.

7. **Analytics & AI Debt Simplification**:
   - Interactive category spending breakdown.
   - AI Debt Minimization matrix that collapses multi-party circular debts into the minimum number of direct PayPal transfers.

8. **Settings & Real-Time API Health**:
   - Live ping tool to probe Tanishq's FastAPI server (`GET /api/health`).
   - Latency monitor.
   - Light and Dark mode toggle.

---

## 📡 Teammate API Integration Contracts

| Teammate | Service | Endpoint | Contract |
|---|---|---|---|
| **Tanishq** | Health Check | `GET /api/health` | Returns `{ status: "healthy", version: "1.0.0" }` |
| **Tanishq** | Groups API | `GET /api/groups`, `POST /api/groups` | Group schema with member list and total balances |
| **Tanishq** | Expenses API | `GET /api/expenses`, `POST /api/expenses` | Expense schema with `splitDetails: [{ userId, share, isPaid }]` |
| **Pawan** | AI Receipt OCR | `POST /api/receipts/extract` | `multipart/form-data` with `receipt` file; returns `{ merchant, date, total, tax, tip, items: [{ name, price, quantity }] }` |
| **Tanay** | PayPal Create Order | `POST /api/payments/paypal/create-order` | JSON `{ amount, currency, receiverEmail, payerId }` -> `{ orderId, status }` |
| **Tanay** | PayPal Capture Order | `POST /api/payments/paypal/capture-order` | JSON `{ orderId, amount, payerId, receiverEmail }` -> `{ captureId, status: "COMPLETED" }` |

---

## 🛠 Tech Stack

- **React 19**
- **Vite 8**
- **Tailwind CSS v4** (`@tailwindcss/vite`)
- **Lucide React** (Fintech iconography)
- **Canvas Confetti** (User delight)
- **Native Fetch API** with resilient offline fallback
