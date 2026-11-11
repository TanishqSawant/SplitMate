/**
 * SplitMate API Client Service Layer
 * 
 * Provides unified request execution, timeout handling, error normalization,
 * and resilient mock fallback for hackathon presentations.
 */

import { API_ENDPOINTS } from './endpoints';
import {
  MOCK_USERS,
  MOCK_GROUPS,
  MOCK_EXPENSES
} from './mockData';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
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
        this.notifyStatus(false);
        console.warn(`[SplitMate API] FastAPI backend offline at ${url}. Falling back to resilient mock service.`, err);
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

    // 5. AI Receipt Extraction (Pawan's contract)
    if (endpoint === API_ENDPOINTS.RECEIPTS.UPLOAD) {
      // Simulate Pawan's AI vision extraction response
      await new Promise((r) => setTimeout(r, 1200));
      return {
        id: `receipt_${Date.now()}`,
        original_filename: 'demo-receipt.jpg',
        merchant_name: 'Artisan Cafe & Grill',
        date: new Date().toISOString().split('T')[0],
        invoiceNumber: `INV-${Math.floor(100000 + Math.random() * 900000)}`,
        currency: 'USD',
        tax: 7.20,
        tip: 12.00,
        subtotal: 78.50,
        total: 97.70,
        extraction_status: 'completed',
        confidence: 0.97,
        items: [
          { id: 'ext_1', item_name: 'Signature Truffle Burger', quantity: 2, total_price: 38.00 },
          { id: 'ext_2', item_name: 'Sweet Potato Truffle Fries', quantity: 1, total_price: 11.50 },
          { id: 'ext_3', item_name: 'Artisan Lemonade', quantity: 2, total_price: 14.00 },
          { id: 'ext_4', item_name: 'Chocolate Molten Cake', quantity: 1, total_price: 15.00 },
        ]
      };
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
