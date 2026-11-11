/**
 * SplitMate API Client Service Layer
 * 
 * Provides unified request execution, timeout handling, error normalization,
 * and resilient mock fallback for hackathon presentations.
 */

import { API_ENDPOINTS } from './endpoints.js';
import {
  MOCK_USERS,
  MOCK_GROUPS,
  MOCK_EXPENSES
} from './mockData.js';

const BASE_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) || 'http://localhost:8000/api';
const DEFAULT_TIMEOUT_MS = 6000;

class ApiClient {
  constructor() {
    this.baseURL = BASE_URL;
    this.isBackendAvailable = null; // null: unknown, true: online, false: offline/mock
    this.onStatusChangeCallbacks = new Set();
    this.authToken = typeof window !== 'undefined' ? localStorage.getItem('splitmate_token') : null;
  }

  setAuthToken(token) {
    this.authToken = token;
    if (typeof window !== 'undefined') {
      if (token) {
        localStorage.setItem('splitmate_token', token);
      } else {
        localStorage.removeItem('splitmate_token');
      }
    }
  }

  getAuthToken() {
    if (!this.authToken && typeof window !== 'undefined') {
      this.authToken = localStorage.getItem('splitmate_token');
    }
    return this.authToken;
  }

  subscribeStatus(callback) {
    this.onStatusChangeCallbacks.add(callback);
    callback({
      isOnline: this.isBackendAvailable,
      baseURL: this.baseURL,
    });
    return () => this.onStatusChangeCallbacks.delete(callback);
  }

  notifyStatus(isOnline) {
    if (this.isBackendAvailable !== isOnline) {
      this.isBackendAvailable = isOnline;
      this.onStatusChangeCallbacks.forEach((cb) =>
        cb({ isOnline: this.isBackendAvailable, baseURL: this.baseURL })
      );
    }
  }

  /**
   * Health check to Tanishq's FastAPI backend
   */
  async checkHealth() {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);

      // The health router is mounted at /health (outside the /api-prefixed routers).
      const healthBaseURL = this.baseURL.replace(/\/api\/?$/, '');
      const response = await fetch(`${healthBaseURL}${API_ENDPOINTS.HEALTH}`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (response.ok) {
        const data = await response.json();
        this.notifyStatus(true);
        return { online: true, data };
      }
      this.notifyStatus(false);
      return { online: false, error: 'Status not OK' };
    } catch {
      this.notifyStatus(false);
      return { online: false, error: 'Unreachable' };
    }
  }

  /**
   * Generic request executor with timeout, JWT propagation, and selective fallback
   */
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options.timeout || DEFAULT_TIMEOUT_MS);

    const token = this.getAuthToken();
    const headers = {
      'Accept': 'application/json',
      ...(!options.isFormData && { 'Content-Type': 'application/json' }),
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      ...options.headers,
    };

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        const detail =
          errorBody.detail ||
          errorBody.message ||
          `HTTP ${response.status}: ${response.statusText}`;

        if (response.status === 401) {
          console.warn('[SplitMate API] 401 Unauthorized: Session token is missing or expired.');
        } else if (response.status === 403) {
          console.warn('[SplitMate API] 403 Forbidden: Caller lacks permission for this action.');
        }

        const error = new Error(detail);
        error.status = response.status;
        error.detail = detail;
        throw error;
      }

      this.notifyStatus(true);
      return await response.json();
    } catch (err) {
      clearTimeout(timeoutId);
<<<<<<< HEAD
      // If server is unreachable, timed out, or offline, mark backend offline and provide mock response
      const isNetworkError =
        err.name === 'AbortError' ||
        err.name === 'TypeError' ||
        err.message?.toLowerCase().includes('failed to fetch') ||
        err.message?.toLowerCase().includes('fetch failed') ||
        err.message?.toLowerCase().includes('networkerror') ||
        err.message?.toLowerCase().includes('connection refused') ||
        Boolean(err.cause);

      if (isNetworkError) {
=======

      // Disable mock fallback for all payment routes:
      // Real integration testing requires genuine backend errors, never synthetic IDs.
      const isPaymentEndpoint =
        typeof endpoint === 'string' &&
        (endpoint.includes('/payments') || endpoint.includes('initialize-payments'));

      if (isPaymentEndpoint) {
        this.notifyStatus(false);
        console.error(`[SplitMate API] Payment endpoint error (${url}): ${err.message}`);
        throw err;
      }

      // If server is unreachable or offline, mark backend offline and provide mock response
      if (err.name === 'AbortError' || err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
>>>>>>> feature/paypal-sandbox
        this.notifyStatus(false);
        console.warn(`[SplitMate API] FastAPI backend offline at ${url}. Falling back to resilient mock service.`);
        return this.handleMockFallback(endpoint, options);
      }
      throw err;
    }
  }

  /**
   * Mock fallback handler for seamless demo resilience
   */
  async handleMockFallback(endpoint, options) {
    await new Promise((r) => setTimeout(r, 400)); // Simulate realistic network latency

    const method = (options.method || 'GET').toUpperCase();

    // 1. Health
    if (endpoint === API_ENDPOINTS.HEALTH) {
      return { status: 'healthy', version: '1.0.0-mock', service: 'SplitMate Mock Service' };
    }

    // 2. Auth Current User
    if (endpoint === API_ENDPOINTS.AUTH.CURRENT_USER) {
      return MOCK_USERS[0];
    }

    // 3. Groups List
    if (endpoint === API_ENDPOINTS.GROUPS.LIST) {
      if (method === 'GET') return MOCK_GROUPS;
      if (method === 'POST') {
        const body = JSON.parse(options.body || '{}');
        const newGroup = {
          id: `grp_${Date.now()}`,
          name: body.name || 'New Group',
          description: body.description || '',
          category: body.category || 'General',
          currency: body.currency || 'USD',
          createdAt: new Date().toISOString().split('T')[0],
          members: [
            { userId: 'usr_dhruv', role: 'Admin' },
            ...(body.memberIds || []).map((id) => ({ userId: id, role: 'Member' }))
          ],
          totalExpenses: 0,
          userBalance: 0,
        };
        return newGroup;
      }
    }

    // 4. Expenses List
    if (endpoint === API_ENDPOINTS.EXPENSES.LIST) {
      if (method === 'GET') return MOCK_EXPENSES;
      if (method === 'POST') {
        const body = JSON.parse(options.body || '{}');
        const newExpense = {
          id: `exp_${Date.now()}`,
          groupId: body.groupId,
          description: body.description,
          amount: parseFloat(body.amount),
          currency: body.currency || 'USD',
          category: body.category || 'General',
          paidBy: body.paidBy || 'usr_dhruv',
          date: body.date || new Date().toISOString().split('T')[0],
          receiptId: body.receiptId || null,
          splitType: body.splitType || 'EQUAL',
          splitDetails: body.splitDetails || []
        };
        return newExpense;
      }
    }

    // 5. AI Receipt Extraction (Never fabricate fake OCR results)
    // The frontend calls POST /receipts/upload then polls GET /receipts/{id}.
    // If the backend is unreachable during upload or poll, throw — do NOT return mock receipt data.
    if (endpoint === API_ENDPOINTS.RECEIPTS.UPLOAD) {
      // Per hackathon safety rules: Never invent receipt details or return unrelated demo data for user uploads.
      throw new Error(
        'Unable to connect to the receipt extraction service. Please ensure the backend server is running on http://localhost:8000.'
      );
    }
    // Also block polling fallback
    if (typeof endpoint === 'string' && endpoint.startsWith('/receipts/')) {
      throw new Error(
        'Unable to connect to the receipt extraction service. Please ensure the backend server is running on http://localhost:8000.'
      );
    }

    // 6. PayPal payments — mock fallback strictly disabled
    if (
      endpoint === API_ENDPOINTS.PAYMENTS.CREATE_ORDER ||
      endpoint === API_ENDPOINTS.PAYMENTS.CAPTURE_ORDER ||
      (typeof endpoint === 'string' && endpoint.includes('/payments'))
    ) {
      throw new Error(
        'Mock payments disabled. PayPal Sandbox testing requires a running FastAPI backend with configured credentials.'
      );
    }

    // Default fallback
    return { ok: true, message: 'Simulated mock response' };
  }
}

export const apiClient = new ApiClient();
