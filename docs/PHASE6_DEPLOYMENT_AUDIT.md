# SPLITMATE — PHASE 6: INITIAL PRE-REMEDIATION DEPLOYMENT AUDIT

**Date:** November 11, 2026
**Document Classification:** Initial Pre-Remediation Baseline Audit
**Auditor:** SplitMate QA & Integration Team (Sunil, Lead QA; Tanishq, Backend; Dhruv, Frontend; Pawan, AI Vision; Tanay, PayPal)
**Baseline Audit Verdict:** **NOT READY FOR PRODUCTION (BLOCKING ISSUES IDENTIFIED)**
**Document Scope:** Historical baseline capturing application state prior to Phase 6 remediation
**Version Target:** 1.0.0-rc1

---

## 1. Executive Summary & Baseline Verdict

> [!NOTE]
> **Initial Pre-Remediation Audit Notice:**
> This document records the **initial pre-remediation deployment readiness audit** performed on SplitMate prior to executing Phase 6 remediation work.
>
> The findings, risk evaluations, and blocker counts documented below represent the architectural and operational state **before** remediation took place. For the implemented solutions, hardened architecture, and full test suite verification results, refer to `docs/PHASE6_FINAL_REPORT.md`.

SplitMate has achieved complete functional integration across all core user flows: group creation, penny-exact itemized expense splitting, dual-engine AI receipt extraction (Google Gemini Vision + offline RapidOCR ONNX heuristic fallback), and PayPal sandbox checkout. The automated test suite achieves **100% pass rate** (52/52 backend tests passing at baseline, zero warnings/errors on `npm run build`).

However, this strict pre-remediation production-readiness audit reveals **7 Critical**, **8 High**, **6 Medium**, and **3 Low** severity architectural and operational blockers that must be resolved before deploying to live users on public infrastructure.

> [!CAUTION]
> **Baseline Pre-Remediation Verdict: NOT READY FOR PRODUCTION**
> Under no circumstances should SplitMate be deployed to production in this pre-remediation state. Deploying without remediation would result in immediate session dropouts on server restart/scaling, user data loss on container rebuilds, cross-origin request blocks (CORS), broken client routing, and unauthenticated access to group financial records.

### Issue Summary Matrix

| Category | Critical | High | Medium | Low | Total |
|---|:---:|:---:|:---:|:---:|:---:|
| 1. Frontend Production Config | 1 | 2 | 1 | 0 | **4** |
| 2. Backend Production Config | 1 | 2 | 1 | 0 | **4** |
| 3. Environment & Secrets | 1 | 1 | 1 | 1 | **4** |
| 4. Database & Persistence | 2 | 1 | 0 | 0 | **3** |
| 5. CORS & Production Networking | 1 | 1 | 0 | 0 | **2** |
| 6. Authentication & Authorization | 1 | 1 | 1 | 0 | **3** |
| 7. Receipt Storage & AI Processing | 0 | 1 | 1 | 1 | **3** |
| 8. PayPal Sandbox vs Live | 0 | 0 | 1 | 1 | **2** |
| 9. Logging & Observability | 0 | 0 | 1 | 0 | **1** |
| 10. Containerization & CI/CD | 0 | 0 | 1 | 0 | **1** |
| **TOTAL** | **7** | **8** | **8** | **3** | **26** |

---

## 2. In-Depth 10-Area Deployment Audit

---

### Area 1: Frontend Production Configuration (React / Vite)

* **Current Implementation:** Vite 8.3.6, React 19.3.1, Tailwind CSS v4.3.5. `npm run build` generates optimized chunks in `dist/` (HTML: 1.15 kB, CSS: 69.38 kB, JS: 388.24 kB).
* **Audit Findings:**
  1. **CRITICAL — Hardcoded Localhost in Static Bundle:** `frontend/.env` defines `VITE_API_BASE_URL=http://127.0.0.1:8000/api`. In Vite, environment variables prefixed with `VITE_` are statically compiled into the client JavaScript bundle at build time. Once deployed to a public CDN (e.g. Vercel, Netlify, Cloudflare Pages), external users' browsers will make API calls to `http://127.0.0.1:8000/api` on their own local laptops/smartphones, resulting in immediate `ERR_CONNECTION_REFUSED`.
  2. **HIGH — Silent Mock Fallback Masks Real Outages:** In `frontend/src/api/client.js` (`handleMockFallback()`), any network failure or timeout triggers silent fallback to hardcoded mock personas (Dhruv, Tanishq, etc.) and fake transactions. In production, this gives users a false illusion that their expenses and group data were saved when the backend was actually unreachable.
  3. **HIGH — Missing Single-Page App (SPA) Routing Configuration:** No `_redirects` file, Nginx rewrite rule (`try_files $uri /index.html;`), or Vercel `routes` config exists. Navigating directly or refreshing on deep routes (e.g. `/groups/123` or `/scanner`) on standard web servers will yield HTTP 404 Not Found.
  4. **MEDIUM — Lack of Content Security Policy (CSP):** `index.html` has no CSP headers defined to protect against cross-site scripting (XSS) or unauthorized resource injection.

---

### Area 2: Backend Production Configuration (FastAPI / Uvicorn)

* **Current Implementation:** FastAPI 0.115.5 running on Uvicorn 0.32.1 single-process development server.
* **Audit Findings:**
  1. **CRITICAL — Development Server Startup Flags:** The server is currently executed with `--reload` and `DEBUG=True` in `backend/.env`. In production, `--reload` spawns file-watching threads that consume excessive CPU and memory, while `DEBUG=True` exposes detailed Python stack traces, file paths, and environment details in 500 error responses.
  2. **HIGH — Absence of Multi-Worker ASGI Process Manager:** The backend runs on a single Python event-loop worker. Under production concurrency or during CPU-bound OCR processing (which takes 2–4 seconds per image), incoming HTTP requests will queue up, degrading response latency across all users. A production process manager (e.g. `gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app`) is required.
  3. **HIGH — Lifespan Race Condition on Schema Creation:** `backend/app/main.py` executes `Base.metadata.create_all(bind=engine)` inside the ASGI `lifespan` handler. If started with multiple workers, each worker simultaneously attempts DDL schema execution, leading to database lock contention and race conditions.
  4. **MEDIUM — Headless Linux Library Dependency:** `backend/requirements.txt` specifies `opencv-python>=4.8.0`. On headless Linux Docker containers or cloud VMs (Debian/Ubuntu/Alpine), importing standard `cv2` fails with `ImportError: libGL.so.1: cannot open shared object file` unless heavy X11/Mesa packages are installed. Production must specify `opencv-python-headless`.

---

### Area 3: Environment Variables and Secret Management

* **Current Implementation:** Configuration managed via `backend/app/core/config.py` using `pydantic-settings` and `.env`.
* **Audit Findings:**
  1. **CRITICAL — Tracked SQLite Databases in Git History:** While `.gitignore` was updated to ignore `*.db`, `backend/splitmate.db` and `backend/test.db` were already committed in prior commits and remain tracked (`git status` reports `M backend/splitmate.db`). If pushed to a public or team repository, local test data is leaked.
  2. **HIGH — Incomplete `.env.example` Templates:** `backend/.env.example` is missing key configuration variables including `GEMINI_API_KEY`, `GEMINI_MODEL`, and `PAYPAL_MOCK_MODE`. A new DevOps engineer deploying the service would face silent fallback or startup failures.
  3. **MEDIUM — Weak or Default Internal Service Secret:** `INTERNAL_SERVICE_SECRET` is used to authenticate internal background tasks and AI extractors via the `X-Internal-Service-Key` header. If left unconfigured, the verification function returns early without enforcing authentication.
  4. **LOW — Plaintext `.env` Storage:** Production deployments must inject secrets via encrypted cloud secret managers (e.g. AWS Secrets Manager, Doppler, Vault, or platform environment variables in Render/Railway) rather than committing unencrypted files to disk.

---

### Area 4: Database Configuration and Persistence

* **Current Implementation:** SQLAlchemy 2.0 with dynamic SQLite / PostgreSQL compatibility. Currently active connection string: `sqlite:///./splitmate.db`.
* **Audit Findings:**
  1. **CRITICAL — SQLite Used in Active Environment:** SQLite uses database-level write locks. In a production multi-user application, concurrent writes (e.g. two users submitting expenses simultaneously) result in `sqlite3.OperationalError: database is locked`.
  2. **CRITICAL — Ephemeral Container Filesystem Wipes Database:** In modern containerized or PaaS hosting (Docker, AWS ECS, Render, Railway, Fly.io, Heroku), container filesystems are strictly ephemeral. Every code deployment, dyno restart, or auto-scaling event will discard the SQLite file, wiping all groups, users, and financial transactions.
  3. **HIGH — Alembic Migrations Require Native PostgreSQL:** The existing migration `backend/migrations/versions/001_initial_schema.py` explicitly uses `postgresql.UUID` and `postgresql.ENUM`. Attempting to apply migrations on SQLite will fail. The production environment must run managed PostgreSQL 15+ (e.g. Supabase, Neon, AWS RDS, or Render PostgreSQL).

---

### Area 5: CORS and API URL Configuration for Production

* **Current Implementation:** `CORSMiddleware` in `backend/app/main.py` parses comma-separated origins from `settings.CORS_ORIGINS`.
* **Audit Findings:**
  1. **CRITICAL — Strictly Localhost CORS Whitelist:** `CORS_ORIGINS` in `backend/.env` is hardcoded to:
     ```text
     http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000,http://localhost:4173,http://127.0.0.1:4173,http://localhost:8000,http://127.0.0.1:8000
     ```
     No production domain (e.g. `https://splitmate.vercel.app` or `https://app.splitmate.com`) is present. Any cross-origin request originating from a public HTTPS frontend domain will be blocked immediately by browser CORS security.
  2. **HIGH — Vite Development Proxy Inoperative in Production:** `frontend/vite.config.js` defines proxy rules for `/api` and `/health`. This proxy is strictly a local Node.js development server feature and does **not** exist when serving static assets from `dist/` on Nginx or a static CDN.

---

### Area 6: Authentication and Authorization Security

* **Current Implementation:** Token-based session management in `backend/app/api/routes/auth.py`.
* **Audit Findings:**
  1. **CRITICAL — In-Memory Session Store (`_ACTIVE_SESSIONS`):** User sessions are stored in an in-memory dictionary:
     ```python
     _ACTIVE_SESSIONS: dict[str, uuid.UUID] = {}
     ```
     - Any server restart, container redeployment, or auto-scale event wipes all active user sessions instantly, forcing every user to re-login.
     - In a multi-worker (`--workers 4`) or multi-instance architecture, Worker 1 cannot see tokens generated by Worker 2. Requests routed to different workers will return intermittent HTTP 401 Unauthorized errors.
  2. **HIGH — Broken Object-Level Authorization (BOLA / OWASP A01:2021):** Core business endpoints in `groups.py`, `expenses.py`, and `receipts.py` do **not** inject the `get_current_user` dependency. Any anonymous client knowing a UUID can query, create, edit, or delete groups and expenses without logging in.
  3. **MEDIUM — Lack of Brute-Force Rate Limiting:** `/api/auth/login` and `/api/auth/register` do not enforce rate limiting (e.g. `slowapi` or Redis token bucket). An attacker can perform dictionary brute-force attacks against user passwords.

---

### Area 7: Receipt Upload and AI Extraction in Production Configuration

* **Current Implementation:** Files uploaded via `/api/receipts/upload`, validated with magic bytes, saved to `backend/uploads/{uuid}.{ext}`, extracted via Gemini Vision or offline RapidOCR.
* **Audit Findings:**
  1. **HIGH — Ephemeral Local Disk Storage:** Uploaded receipt images and PDFs are stored in the local `uploads/` folder. On ephemeral cloud containers, previously uploaded receipts will disappear on container restart, returning 404 when viewing receipt thumbnails or running delayed extraction.
  2. **MEDIUM — Synchronous OCR Inference Blocks Event Loop:** RapidOCR ONNX inference is CPU-intensive. Running inference synchronously inside the API route handler blocks the worker process for 2–4 seconds per image. High volume uploads should be offloaded to an asynchronous background worker (e.g. Celery, ARQ, or FastAPI `BackgroundTasks`).
  3. **LOW — Storage Capacity Management:** No cleanup or retention policy exists for stored receipt images, which can lead to disk exhaustion if local volumes are used.

---

### Area 8: PayPal Sandbox versus Live Configuration

* **Current Implementation:** `PayPalService` configured to point to `https://api-m.sandbox.paypal.com`.
* **Audit Findings:**
  1. **MEDIUM — Silent Mock Payment Fallback:** When PayPal credentials are blank or invalid, `PayPalService` automatically falls back to generating mock IDs (`MOCK-ORD-...`, `MOCK-CAP-...`) and returns `status: COMPLETED`. In a production environment with real users, a misconfigured credential should return an explicit error (HTTP 502/503) rather than silently pretending debts have been paid.
  2. **LOW — Missing Webhook Listener:** The application captures payments synchronously from the client. While functional, production enterprise PayPal integrations typically register a webhook endpoint to asynchronously reconcile disputes, chargebacks, and delayed captures.
  > [!NOTE]
  > As instructed, PayPal Sandbox configuration is preserved and must NOT be switched to Live during audit or staging.

---

### Area 9: Logging, Observability, and Error Handling

* **Current Implementation:** Basic Python logging across services. `/health` and `/api/health` return HTTP 200.
* **Audit Findings:**
  1. **MEDIUM — Absence of Structured JSON Logging:** Application logs output plain text. In production cloud environments (AWS CloudWatch, Datadog, Grafana Loki, Papertrail), logs must be formatted as structured JSON containing timestamp, log level, request ID, endpoint, and user context for efficient querying and alerting.

---

### Area 10: Containerization and CI/CD

* **Current Implementation:** Native local execution (Windows PowerShell / Python venv / Vite).
* **Audit Findings:**
  1. **MEDIUM — Absence of Container Artifacts & CI Pipeline:** No `Dockerfile`, `.dockerignore`, or `docker-compose.yml` exists in the repository. No automated GitHub Actions workflow is present to validate tests before merge.

---

## 3. Comprehensive Issue Classification Table

| Issue ID | Area | Severity | Description | Remediation Required |
|:---:|:---|:---:|:---|:---|
| **ISSUE-01** | Frontend | **CRITICAL** | `VITE_API_BASE_URL` hardcoded to `127.0.0.1:8000` in static bundle. | Inject production backend URL (e.g. `https://api.splitmate.com/api`) during production build. |
| **ISSUE-02** | Backend | **CRITICAL** | Backend running with `--reload` and `DEBUG=True`. | Set `DEBUG=False`, `APP_ENV=production`, and use production ASGI command. |
| **ISSUE-03** | Auth | **CRITICAL** | In-memory `_ACTIVE_SESSIONS` dictionary resets on restart and fails across multiple workers. | Migrate to stateless signed JWTs (`python-jose` / `pyjwt`) or Redis/Postgres session store. |
| **ISSUE-04** | Database | **CRITICAL** | SQLite active in production configuration (`splitmate.db`). | Switch `DATABASE_URL` to managed PostgreSQL 15+. |
| **ISSUE-05** | Database | **CRITICAL** | Ephemeral container storage will destroy SQLite database on restart. | Provision persistent managed database (Supabase, Neon, or RDS). |
| **ISSUE-06** | CORS | **CRITICAL** | `CORS_ORIGINS` only whitelists localhost and 127.0.0.1. | Add production frontend domain(s) to `CORS_ORIGINS`. |
| **ISSUE-07** | Git/Secrets| **CRITICAL** | `backend/splitmate.db` tracked in git repository history. | Remove database from git cache: `git rm --cached backend/splitmate.db backend/test.db`. |
| **ISSUE-08** | Frontend | **HIGH** | Silent mock fallback masks real API outages. | Add `VITE_ENABLE_MOCK_FALLBACK=false` for production builds to show honest error states. |
| **ISSUE-09** | Frontend | **HIGH** | Missing SPA rewrite rules for client-side routing. | Add Nginx `try_files` or Vercel/Netlify rewrite rules to redirect all routes to `index.html`. |
| **ISSUE-10** | Backend | **HIGH** | Single-worker Uvicorn cannot handle concurrent OCR/API load. | Use Gunicorn with 4 Uvicorn workers (`gunicorn -w 4 -k uvicorn.workers.UvicornWorker`). |
| **ISSUE-11** | Backend | **HIGH** | `Base.metadata.create_all()` in lifespan causes multi-worker race conditions. | Execute schema migrations via Alembic command prior to server startup. |
| **ISSUE-12** | Backend | **HIGH** | `opencv-python` requires X11 libraries on Linux containers. | Replace with `opencv-python-headless>=4.8.0` in `requirements.txt`. |
| **ISSUE-13** | Secrets | **HIGH** | `.env.example` missing AI and PayPal environment variables. | Update `.env.example` with all required production keys and instructions. |
| **ISSUE-14** | Auth | **HIGH** | Groups, Receipts, and Expenses endpoints lack authentication checks. | Enforce `Depends(get_current_user)` on protected data mutations. |
| **ISSUE-15** | Storage | **HIGH** | Local `uploads/` directory loses uploaded receipts on container restart. | Configure S3-compatible cloud object store (AWS S3, Cloudflare R2, or persistent volume). |
| **ISSUE-16** | Frontend | **MEDIUM** | Missing Content Security Policy (CSP) headers. | Configure standard CSP meta tags in `index.html` or web server headers. |
| **ISSUE-17** | Auth | **MEDIUM** | Missing rate-limiting on login and registration endpoints. | Implement rate limiting with `slowapi` or Nginx `limit_req`. |
| **ISSUE-18** | PayPal | **MEDIUM** | Silent mock mode fallback risks false payment settlement in production. | Disable `PAYPAL_MOCK_MODE` in production; fail explicitly with HTTP 502 if sandbox is unreachable. |
| **ISSUE-19** | Logging | **MEDIUM** | Plain text logs without correlation IDs or structured JSON. | Implement JSON logging formatter with request trace IDs. |
| **ISSUE-20** | CI/CD | **MEDIUM** | No automated GitHub Actions workflow for linting, testing, and builds. | Create `.github/workflows/ci.yml` running pytest and npm build on pull requests. |
| **ISSUE-21** | AI Vision | **MEDIUM** | Synchronous OCR blocks request thread for 2–4 seconds. | Offload OCR execution to background tasks for high-volume uploads. |
| **ISSUE-22** | Secrets | **LOW** | Internal service secret defaults to empty string. | Require non-empty 256-bit secret in production settings validator. |
| **ISSUE-23** | PayPal | **LOW** | Missing asynchronous webhook listener. | Add PayPal webhook route for post-capture reconciliation. |
| **ISSUE-24** | Storage | **LOW** | No file retention or cleanup policy for uploaded receipts. | Implement 30-day lifecycle expiration policy for temporary scans. |

---

## 4. Production Deployment Plan & Hosting Architecture

### 4.1 Recommended Hosting Architecture

```mermaid
flowchart TD
    Client["Client Browsers (Desktop & Mobile)"] --> CDN["Cloudflare / Fastly Edge Network"]

    subgraph Frontend["Frontend Tier (Vercel / Netlify / Cloudflare Pages)"]
        SPA["Vite React SPA (dist/)"]
        Rewrite["SPA Rewrite Rules: /* -> /index.html"]
    end

    subgraph Backend["Backend Tier (Render / Railway / AWS ECS Fargate)"]
        ReverseProxy["Nginx / Caddy Reverse Proxy (HTTPS / SSL)"]
        Gunicorn["Gunicorn Process Manager (4 Uvicorn Workers)"]
        FastAPI["FastAPI 0.115 Application"]
        ReverseProxy --> Gunicorn --> FastAPI
    end

    subgraph DataTier["Data & Storage Tier"]
        Postgres[("Managed PostgreSQL 15+ (Neon / Supabase / AWS RDS)")]
        R2[("Cloud Object Storage (Cloudflare R2 / AWS S3)")]
    end

    subgraph ExternalServices["External APIs"]
        Gemini["Google Gemini 1.5/2.5 Flash API"]
        PayPal["PayPal Sandbox REST API (v2/checkout)"]
    end

    CDN --> SPA
    SPA -- "REST API (Bearer JWT)" --> ReverseProxy
    FastAPI --> Postgres
    FastAPI --> R2
    FastAPI --> Gemini
    FastAPI --> PayPal
```

#### Recommended Cloud Provider Setup:
* **Frontend:** **Vercel** or **Cloudflare Pages** (Zero-maintenance global CDN, automatic SSL, instant previews, edge caching).
* **Backend:** **Render.com** or **Railway.app** (Native Python 3.13 support, automatic HTTPS, integrated health checks, horizontal worker scaling).
* **Database:** **Neon** or **Supabase** (Serverless PostgreSQL with auto-backups, connection pooling, and SSL encryption).
* **Receipt Storage:** **Cloudflare R2** or **AWS S3** (Zero egress fees on R2, S3-compatible API, persistent encrypted file storage).

---

### 4.2 Step-by-Step Production Launch Checklist

To bring SplitMate to full production launch readiness, execute the following four phases:

#### Phase A: Security & Configuration Hardening
1. **Remove Tracked Databases from Git:**
   ```bash
   git rm --cached backend/splitmate.db backend/test.db
   git commit -m "security: untrack SQLite test databases"
   ```
2. **Switch to Stateless JWT Authentication:**
   Replace the in-memory `_ACTIVE_SESSIONS` dictionary with cryptographically signed JWT tokens (`HS256` using `SECRET_KEY`) with a 24-hour expiration window.
3. **Enforce Authorization Dependencies:**
   Protect private routes in `groups.py`, `expenses.py`, and `receipts.py` using `Depends(get_current_user)`.
4. **Environment Configuration for Production:**
   - In `backend/.env`: Set `APP_ENV=production`, `DEBUG=False`.
   - Update `CORS_ORIGINS` to include your production frontend domain (e.g. `https://splitmate.vercel.app`).
   - In `frontend/.env.production`: Set `VITE_API_BASE_URL=https://api.splitmate.com/api` and `VITE_ENABLE_MOCK_FALLBACK=false`.

#### Phase B: Database & Storage Migration
1. **Provision Managed PostgreSQL:**
   Obtain a PostgreSQL connection string (e.g. from Neon or Supabase) with SSL mode required:
   ```text
   DATABASE_URL=postgresql://user:password@ep-host.neon.tech/splitmate?sslmode=require
   ```
2. **Execute Alembic Migrations:**
   ```bash
   cd backend
   alembic upgrade head
   ```
3. **Configure Persistent Receipt Storage:**
   Configure an S3-compatible client or mount a persistent disk volume on `/app/uploads` so uploaded receipts survive container restarts.

#### Phase C: Production Containerization & Build
1. **Switch to Headless OpenCV:**
   In `backend/requirements.txt`, update `opencv-python>=4.8.0` to `opencv-python-headless>=4.8.0`.
2. **Add Multi-Stage Dockerfiles:**
   - **Backend Dockerfile:** Python 3.13-slim base, install dependencies, run via `gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 app.main:app`.
   - **Frontend Dockerfile (or Vercel config):** Node 20 base, `npm run build`, serve via Nginx with SPA fallback (`try_files $uri /index.html;`).
3. **Automate CI/CD:**
   Set up `.github/workflows/ci.yml` to automatically run tests (`pytest tests/`) and frontend build (`npm run build`) on every push.

#### Phase D: Pre-Launch Smoke Testing & Validation
1. Verify `/health` and `/api/health` return HTTP 200 with database connectivity status.
2. Register a new user, log in, and verify the issued JWT token persists across container restarts.
3. Upload a sample receipt and confirm that RapidOCR / Gemini Vision extracts line items and the image remains viewable after server reload.
4. Execute a PayPal Sandbox transaction and verify that the payment status transitions from `pending` to `order_created` to `captured`.
5. Run automated load testing (e.g. Locust or k6) simulating 50 concurrent users.

---

## 5. Conclusion & Baseline Audit Summary

SplitMate has solid algorithmic foundations—including penny-exact splitting algorithms, robust offline OCR fallbacks, and polished UI components. Once the **7 Critical** architectural remediation items (stateless JWTs, PostgreSQL migration, persistent file storage, production CORS/URLs, and disabling debug mode) and associated High priority blockers are implemented as planned in `docs/PHASE6_REMEDIATION_PLAN.md`, SplitMate will be fully prepared for public launch. Implementation outcomes and verification metrics are documented in `docs/PHASE6_FINAL_REPORT.md`.
