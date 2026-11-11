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
const USE_MOCK_API = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_USE_MOCK_API === 'true');
const DEFAULT_TIMEOUT_MS = 10000;

class ApiClient {
  constructor() {
    this.baseURL = BASE_URL;
    this.isBackendAvailable = null; // null: unknown, true: online, false: offline/mock
    this.onStatusChangeCallbacks = new Set();
  }

  getToken() {
    try {
      return localStorage.getItem('splitmate_access_token');
    } catch {
      return null;
    }
  }

  setToken(token) {
    try {
      if (token) {
        localStorage.setItem('splitmate_access_token', token);
      } else {
        localStorage.removeItem('splitmate_access_token');
      }
    } catch {
      // ignore storage errors
    }
  }

  clearToken() {
    try {
      localStorage.removeItem('splitmate_access_token');
    } catch {
      // ignore storage errors
    }
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
   * Generic request executor with JWT authentication and error handling
   */
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options.timeout || DEFAULT_TIMEOUT_MS);

    const token = this.getToken();
    const headers = {
      'Accept': 'application/json',
      ...(!options.isFormData && { 'Content-Type': 'application/json' }),
      ...(token && !options.skipAuth ? { 'Authorization': `Bearer ${token}` } : {}),
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
        // Handle expired session / invalid token (401) without incorrectly logging out on 403
        if (response.status === 401) {
          this.clearToken();
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('splitmate_auth_unauthorized'));
          }
        }

        const errorBody = await response.json().catch(() => ({}));
        const errorDetail = errorBody.detail || errorBody.message || `HTTP ${response.status}: ${response.statusText}`;
        const errorMsg = typeof errorDetail === 'string' ? errorDetail : JSON.stringify(errorDetail);
        const err = new Error(errorMsg);
        err.status = response.status;
        err.body = errorBody;
        throw err;
      }

      this.notifyStatus(true);
      return await response.json();
    } catch (err) {
      clearTimeout(timeoutId);

      // If server is unreachable, timed out, or network failed
      const isNetworkError =
        err.name === 'AbortError' ||
        err.name === 'TypeError' ||
        err.message?.toLowerCase().includes('failed to fetch') ||
        err.message?.toLowerCase().includes('fetch failed') ||
        err.message?.toLowerCase().includes('networkerror') ||
        err.message?.toLowerCase().includes('connection refused') ||
        Boolean(err.cause);

      if (isNetworkError) {
        this.notifyStatus(false);

        // Security rule: Never mock payments or receipts
        if (typeof endpoint === 'string' && (endpoint.includes('/payments') || endpoint.includes('/receipts'))) {
          throw new Error('Unable to connect to the backend service. Please ensure the server is running on http://localhost:8000.');
        }

        if (USE_MOCK_API) {
          console.warn(`[SplitMate API] FastAPI backend offline at ${url}. Falling back to mock service.`);
          return this.handleMockFallback(endpoint, options);
        }

        throw new Error(`Unable to connect to backend server at ${url}. Please ensure the server is running on http://localhost:8000.`);
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

    // 5. AI Receipt Extraction & PayPal Payments (Never mock real financial transactions)
    if (typeof endpoint === 'string' && (endpoint.includes('/receipts') || endpoint.includes('/payments'))) {
      throw new Error(
        'Real PayPal payments and AI receipt extraction require the backend service to be running.'
      );
    }

    // Default fallback
    return { ok: true, message: 'Simulated mock response' };
  }
}

export const apiClient = new ApiClient();
