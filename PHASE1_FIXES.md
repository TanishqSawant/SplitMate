# SplitMate – Phase 1 Fixes

## Changes made

1. **B1 – `httpx` dependency:** Already present in `backend/requirements.txt` (`httpx==0.28.0`); no change required.
2. **B2 – Health check:** Updated `frontend/src/api/client.js` so the health check targets the backend's root `/health` route. Other API calls continue to use the `/api` base URL.
3. **B3 – API prefixes:** Verified the frontend base URL defaults to `http://localhost:8000/api` and the groups, expenses, receipts, and payments routers use `/api/...` prefixes. Their relative endpoint paths are therefore correct; no blanket prefix change was made.
4. **B4 – Receipt upload:** Added the `/receipts/upload` endpoint constant and changed the multipart field to `file`, matching FastAPI's `upload_receipt(file: UploadFile, ...)` route.

## Important remaining integration gap

The current backend receipt routes upload a file and accept extraction results at `POST /api/receipts/{receipt_id}/extraction`; they do not invoke an OCR/AI extraction service. When the live backend returns a newly uploaded receipt with no items, the frontend now reports that upload succeeded but AI extraction is not connected. The offline mock fallback continues to provide demo receipt items.

## Validation

- Python backend source passed `python -m compileall -q backend/app`.
- JavaScript API client and endpoint files passed `node --check`.
- A full Vite build and live API integration test were not run in this environment.

## Not included in this phase

PayPal modal and backend payment lifecycle wiring (B5/B6), complete receipt OCR integration, and full end-to-end testing remain outstanding.
