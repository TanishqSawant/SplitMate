/**
 * SplitMate API Client Service Layer
 * 
 * Provides unified request execution, timeout handling, error normalization,
 * and resilient mock fallback for offline hackathon presentations.
 */

import { API_ENDPOINTS } from './endpoints';
import {
  MOCK_USERS,
  MOCK_GROUPS,
  MOCK_EXPENSES,
  MOCK_PAYPAL_TRANSACTIONS
} from './mockData';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api';
const DEFAULT_TIMEOUT_MS = 30000;

class ApiClient {
  constructor() {
    this.baseURL = BASE_URL;
    this.isBackendAvailable = null; // null: unknown, true: online, false: offline/mock
    this.onStatusChangeCallbacks = new Set();
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
   * Health check to FastAPI backend with dual-host resilience (127.0.0.1 & localhost)
   */
  async checkHealth() {
    // Gather candidate hosts to handle IPv4 (127.0.0.1) vs IPv6 (localhost) on Windows
    const candidates = [];
    const configuredBase = this.baseURL.replace(/\/api\/?$/, '');
    candidates.push(configuredBase);

    if (configuredBase.includes('localhost:8000')) {
      candidates.push(configuredBase.replace('localhost:8000', '127.0.0.1:8000'));
    } else if (configuredBase.includes('127.0.0.1:8000')) {
      candidates.push(configuredBase.replace('127.0.0.1:8000', 'localhost:8000'));
    }

    for (const host of candidates) {
      for (const healthPath of [API_ENDPOINTS.HEALTH, '/api/health']) {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 3500);

          const response = await fetch(`${host}${healthPath}`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' },
            signal: controller.signal,
          });

          clearTimeout(timeoutId);

          if (response.ok) {
            const data = await response.json();
            if (host !== configuredBase) {
              this.baseURL = `${host}/api`;
              console.info(`[SplitMate API] Connected to active host: ${this.baseURL}`);
            }
            this.notifyStatus(true);
            return { online: true, data };
          }
        } catch {
          // Probe next candidate
        }
      }
    }

    this.notifyStatus(false);
    return { online: false, error: 'Unreachable' };
  }

  /**
   * Generic request executor with timeout and mock fallback
   */
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const controller = new AbortController();
    // Receipt processing with OCR/Vision takes longer; use 90s timeout
    const isReceiptAction = endpoint.startsWith('/receipts/upload') || endpoint.includes('/extract');
    const timeoutMs = options.timeout || (isReceiptAction ? 90000 : DEFAULT_TIMEOUT_MS);
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const headers = {
      'Accept': 'application/json',
      ...(!options.isFormData && { 'Content-Type': 'application/json' }),
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
        throw new Error(errorBody.detail || errorBody.message || `HTTP ${response.status}: ${response.statusText}`);
      }

      this.notifyStatus(true);
      return await response.json();
    } catch (err) {
      clearTimeout(timeoutId);

      // Auto-retry once on alternate host if localhost/127.0.0.1 connection refused
      if ((err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) && !options._retried) {
        let alternateBase = null;
        if (this.baseURL.includes('localhost:8000')) {
          alternateBase = this.baseURL.replace('localhost:8000', '127.0.0.1:8000');
        } else if (this.baseURL.includes('127.0.0.1:8000')) {
          alternateBase = this.baseURL.replace('127.0.0.1:8000', 'localhost:8000');
        }

        if (alternateBase) {
          try {
            this.baseURL = alternateBase;
            return await this.request(endpoint, { ...options, _retried: true });
          } catch {
            // Revert on failure
          }
        }
      }

      // If server is unreachable or offline, mark backend offline and handle fallback
      if (err.name === 'AbortError' || err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
        this.notifyStatus(false);
        const reason = err.name === 'AbortError' ? 'timeout (processing took too long)' : 'connection failed';
        // In production, mock fallback can be explicitly disabled via VITE_ENABLE_MOCK_FALLBACK=false
        const allowMock = import.meta.env.VITE_ENABLE_MOCK_FALLBACK !== 'false';
        if (!allowMock) {
          throw new Error(`SplitMate API is currently offline (${reason}). Please check your connection or try again.`);
        }

        console.warn(`[SplitMate API] Backend unreachable at ${url} (${reason}). Falling back to resilient mock service.`, err);
        return this.handleMockFallback(endpoint, { ...options, isTimeout: err.name === 'AbortError' });
      }
      throw err;
    }
  }

  /**
   * Mock fallback handler for seamless demo resilience
   */
  async handleMockFallback(endpoint, options = {}) {
    await new Promise((r) => setTimeout(r, 300)); // Simulate realistic network latency

    const method = (options.method || 'GET').toUpperCase();

    // 1. Health
    if (endpoint === API_ENDPOINTS.HEALTH) {
      return { status: 'ok', version: '0.1.0-mock', service: 'SplitMate Mock Service' };
    }

    // 2. Auth Current User
    if (endpoint === API_ENDPOINTS.AUTH.CURRENT_USER) {
      return MOCK_USERS[0];
    }

    // 3. Groups
    if (endpoint.startsWith('/groups')) {
      if (method === 'GET') {
        if (endpoint.includes('/members')) {
          return MOCK_USERS.map((u) => ({ id: u.id, name: u.name, email: u.email }));
        }
        return MOCK_GROUPS;
      }
      if (method === 'POST') {
        const body = JSON.parse(options.body || '{}');
        if (endpoint.includes('/members')) {
          return {
            id: `mbr_${Date.now()}`,
            name: body.name || 'Member',
            email: body.email || 'member@example.com',
            created_at: new Date().toISOString(),
          };
        }
        return {
          id: `grp_${Date.now()}`,
          name: body.name || 'New Squad',
          created_at: new Date().toISOString(),
          members: MOCK_USERS.map((u) => ({ userId: u.id, role: 'Member' })),
        };
      }
    }

    // 4. Expenses
    if (endpoint.startsWith('/expenses')) {
      if (method === 'GET') {
        if (endpoint.includes('/splits')) {
          return {
            expense_id: 'exp_mock_1',
            total_amount: 85.70,
            currency: 'USD',
            splits: MOCK_USERS.map((u) => ({
              member_id: u.id,
              member_name: u.name,
              member_email: u.email,
              allocated_subtotal: 15.70,
              allocated_tax: 1.44,
              amount: 17.14,
              currency: 'USD',
            })),
          };
        }
        return MOCK_EXPENSES;
      }
      if (method === 'POST') {
        const body = JSON.parse(options.body || '{}');
        if (endpoint.includes('/assign')) {
          return body.assignments || [];
        }
        if (endpoint.includes('/initialize-payments')) {
          return MOCK_USERS.map((u) => ({
            id: `pay_${Date.now()}_${u.id}`,
            expense_id: `exp_${Date.now()}`,
            member_id: u.id,
            amount: 17.14,
            currency: 'USD',
            paypal_order_id: null,
            paypal_capture_id: null,
            status: 'pending',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }));
        }
        return {
          id: `exp_${Date.now()}`,
          group_id: body.group_id || 'grp_mock',
          receipt_id: body.receipt_id || null,
          total_amount: body.total_amount || 85.70,
          currency: body.currency || 'USD',
          created_at: new Date().toISOString(),
        };
      }
    }

    // 5. Receipts
    if (endpoint.startsWith('/receipts')) {
      if (endpoint.includes('/extract') || endpoint.includes('/upload')) {
        const warning = options.isTimeout
          ? 'Receipt processing timed out. The server took longer than expected to process the receipt. Please try again with a clearer or smaller image.'
          : `Backend server is offline or unreachable at ${this.baseURL}. AI receipt extraction is unavailable. Please verify the backend is running at http://127.0.0.1:8000 and try again.`;
        return {
          id: `rcpt_${Date.now()}`,
          original_filename: 'receipt.jpg',
          merchant_name: null,
          currency: 'USD',
          subtotal: null,
          tax: null,
          total: null,
          extraction_status: 'failed',
          is_fallback: true,
          items: [],
          warnings: [warning],
        };
      }
    }

    // 6. Payments
    if (endpoint.startsWith('/payments')) {
      if (endpoint.includes('/create-order')) {
        return {
          id: `pay_${Date.now()}`,
          paypal_order_id: `MOCK-ORD-${Math.random().toString(36).substring(2, 10).toUpperCase()}`,
          status: 'order_created',
          amount: 25.00,
          currency: 'USD',
        };
      }
      if (endpoint.includes('/capture')) {
        return {
          id: `pay_${Date.now()}`,
          paypal_order_id: 'MOCK-ORD-SUCCESS',
          paypal_capture_id: `MOCK-CAP-${Math.random().toString(36).substring(2, 10).toUpperCase()}`,
          status: 'captured',
          amount: 25.00,
          currency: 'USD',
        };
      }
    }

    // Default fallback
    return { ok: true, message: 'Simulated fallback response' };
  }
}

export const apiClient = new ApiClient();
