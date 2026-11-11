
/**
 * SplitMate API Client Service Layer
 *
 * Provides unified request execution, timeout handling,
 * error normalization, and resilient mock fallback for offline demos.
 */

import { API_ENDPOINTS } from './endpoints.js';
import {
  MOCK_USERS,
  MOCK_GROUPS,
  MOCK_EXPENSES,
} from './mockData.js';

const BASE_URL =
  (typeof import.meta !== 'undefined' &&
    import.meta.env?.VITE_API_BASE_URL) ||
  'http://127.0.0.1:8000/api';

const DEFAULT_TIMEOUT_MS = 30000;

class ApiClient {
  constructor() {
    this.baseURL = BASE_URL;
    this.isBackendAvailable = null;
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

      this.onStatusChangeCallbacks.forEach((callback) =>
        callback({
          isOnline: this.isBackendAvailable,
          baseURL: this.baseURL,
        })
      );
    }
  }

  /**
   * Check backend health using localhost and 127.0.0.1.
   */
  async checkHealth() {
    const candidates = [];
    const configuredBase = this.baseURL.replace(/\/api\/?$/, '');

    candidates.push(configuredBase);

    if (configuredBase.includes('localhost:8000')) {
      candidates.push(
        configuredBase.replace('localhost:8000', '127.0.0.1:8000')
      );
    } else if (configuredBase.includes('127.0.0.1:8000')) {
      candidates.push(
        configuredBase.replace('127.0.0.1:8000', 'localhost:8000')
      );
    }

    for (const host of [...new Set(candidates)]) {
      for (const healthPath of [
        API_ENDPOINTS.HEALTH,
        '/api/health',
      ]) {
        const controller = new AbortController();
        const timeoutId = setTimeout(
          () => controller.abort(),
          3500
        );

        try {
          const response = await fetch(`${host}${healthPath}`, {
            method: 'GET',
            headers: {
              Accept: 'application/json',
            },
            signal: controller.signal,
          });

          if (response.ok) {
            const data = await response.json();

            if (host !== configuredBase) {
              this.baseURL = `${host}/api`;

              console.info(
                `[SplitMate API] Connected to active host: ${this.baseURL}`
              );
            }

            this.notifyStatus(true);

            return {
              online: true,
              data,
            };
          }
        } catch {
          // Try the next host or health endpoint.
        } finally {
          clearTimeout(timeoutId);
        }
      }
    }

    this.notifyStatus(false);

    return {
      online: false,
      error: 'Unreachable',
    };
  }

  /**
   * Execute an API request with timeout and offline fallback.
   */
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const isReceiptAction =
      endpoint.startsWith('/receipts/upload') ||
      endpoint.includes('/extract');

    const timeoutMs =
      options.timeout ||
      (isReceiptAction ? 90000 : DEFAULT_TIMEOUT_MS);

    const headers = {
      Accept: 'application/json',
      ...(!options.isFormData && {
        'Content-Type': 'application/json',
      }),
      ...options.headers,
    };

    const controller = new AbortController();

    const timeoutId = setTimeout(
      () => controller.abort(),
      timeoutMs
    );

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      });

      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));

        throw new Error(
          errorBody.detail ||
            errorBody.message ||
            `HTTP ${response.status}: ${response.statusText}`
        );
      }

      this.notifyStatus(true);

      return await response.json();
    } catch (err) {
      const isNetworkError =
        err.name === 'AbortError' ||
        err.name === 'TypeError' ||
        err.message?.toLowerCase().includes('failed to fetch') ||
        err.message?.toLowerCase().includes('fetch failed') ||
        err.message?.toLowerCase().includes('networkerror') ||
        err.message?.toLowerCase().includes('connection refused');

      if (!isNetworkError) {
        throw err;
      }

      // Retry once using the alternate local host.
      if (!options._retried) {
        let alternateBase = null;

        if (this.baseURL.includes('localhost:8000')) {
          alternateBase = this.baseURL.replace(
            'localhost:8000',
            '127.0.0.1:8000'
          );
        } else if (this.baseURL.includes('127.0.0.1:8000')) {
          alternateBase = this.baseURL.replace(
            '127.0.0.1:8000',
            'localhost:8000'
          );
        }

        if (alternateBase) {
          const originalBase = this.baseURL;

          try {
            this.baseURL = alternateBase;

            return await this.request(endpoint, {
              ...options,
              _retried: true,
            });
          } catch (retryError) {
            this.baseURL = originalBase;

            if (
              retryError.name !== 'AbortError' &&
              retryError.name !== 'TypeError' &&
              !retryError.message?.toLowerCase().includes('failed to fetch') &&
              !retryError.message?.toLowerCase().includes('fetch failed') &&
              !retryError.message?.toLowerCase().includes('networkerror') &&
              !retryError.message?.toLowerCase().includes('connection refused')
            ) {
              throw retryError;
            }

            err = retryError;
          }
        }
      }

      this.notifyStatus(false);

      const reason =
        err.name === 'AbortError'
          ? 'request timed out'
          : 'connection failed';

      console.warn(
        `[SplitMate API] Backend unavailable at ${url}: ${reason}`
      );

      // Never fabricate receipt extraction results.
      if (
        endpoint.startsWith('/receipts/upload') ||
        endpoint.startsWith('/receipts/')
      ) {
        throw new Error(
          'Unable to connect to the receipt extraction service. Please ensure the backend server is running and try again.'
        );
      }

      // Mock fallback can be disabled in production.
      const allowMock =
        typeof import.meta === 'undefined' ||
        import.meta.env?.VITE_ENABLE_MOCK_FALLBACK !== 'false';

      if (!allowMock) {
        throw new Error(
          `SplitMate API is currently offline (${reason}). Please check your connection and try again.`
        );
      }

      return this.handleMockFallback(endpoint, {
        ...options,
        isTimeout: err.name === 'AbortError',
      });
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * Mock fallback handler for demo resilience.
   */
  async handleMockFallback(endpoint, options = {}) {
    await new Promise((resolve) => setTimeout(resolve, 300));

    const method = (options.method || 'GET').toUpperCase();

    // 1. Health
    if (endpoint === API_ENDPOINTS.HEALTH) {
      return {
        status: 'ok',
        version: '0.1.0-mock',
        service: 'SplitMate Mock Service',
      };
    }

    // 2. Current user
    if (endpoint === API_ENDPOINTS.AUTH.CURRENT_USER) {
      return MOCK_USERS[0];
    }

    // 3. Groups
    if (endpoint.startsWith('/groups')) {
      if (method === 'GET') {
        if (endpoint.includes('/members')) {
          return MOCK_USERS.map((user) => ({
            id: user.id,
            name: user.name,
            email: user.email,
          }));
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
          members: MOCK_USERS.map((user) => ({
            userId: user.id,
            role: 'Member',
          })),
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
            splits: MOCK_USERS.map((user) => ({
              member_id: user.id,
              member_name: user.name,
              member_email: user.email,
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
          return MOCK_USERS.map((user) => ({
            id: `pay_${Date.now()}_${user.id}`,
            expense_id: `exp_${Date.now()}`,
            member_id: user.id,
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

    // 5. Receipt extraction
    // Do not return invented receipt data when the backend is unavailable.
    if (
      endpoint === API_ENDPOINTS.RECEIPTS.UPLOAD ||
      endpoint.startsWith('/receipts/')
    ) {
      throw new Error(
        'Unable to connect to the receipt extraction service. Please ensure the backend server is running and try again.'
      );
    }

    // 6. PayPal create order
    if (endpoint === API_ENDPOINTS.PAYMENTS.CREATE_ORDER) {
      const body = JSON.parse(options.body || '{}');

      return {
        orderId: `ORDER-${Math.random()
          .toString(36)
          .substring(2, 11)
          .toUpperCase()}`,
        status: 'CREATED',
        amount: body.amount,
        currency: body.currency || 'USD',
        approvalUrl:
          'https://www.sandbox.paypal.com/checkoutnow?token=mock_sandbox_token',
      };
    }

    // 7. Other payment endpoints
    if (endpoint.startsWith('/payments')) {
      if (endpoint.includes('/create-order')) {
        return {
          id: `pay_${Date.now()}`,
          paypal_order_id: `MOCK-ORD-${Math.random()
            .toString(36)
            .substring(2, 10)
            .toUpperCase()}`,
          status: 'order_created',
          amount: 25.00,
          currency: 'USD',
        };
      }

      if (endpoint.includes('/capture')) {
        return {
          id: `pay_${Date.now()}`,
          paypal_order_id: 'MOCK-ORD-SUCCESS',
          paypal_capture_id: `MOCK-CAP-${Math.random()
            .toString(36)
            .substring(2, 10)
            .toUpperCase()}`,
          status: 'captured',
          amount: 25.00,
          currency: 'USD',
        };
      }
    }

    return {
      ok: true,
      message: 'Simulated fallback response',
    };
  }
}

export const apiClient = new ApiClient();
