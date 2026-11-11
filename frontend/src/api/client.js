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
  'http://localhost:8000/api';

const DEFAULT_TIMEOUT_MS = 30000;

class ApiClient {
  constructor() {
    this.baseURL = BASE_URL;
    this.isBackendAvailable = null;
    this.onStatusChangeCallbacks = new Set();
  }

  getToken() {
    try {
      return (
        localStorage.getItem('splitmate_token') ||
        localStorage.getItem('splitmate_access_token')
      );
    } catch {
      return null;
    }
  }

  setToken(token) {
    try {
      if (token) {
        localStorage.setItem('splitmate_token', token);
        localStorage.setItem('splitmate_access_token', token);
      } else {
        localStorage.removeItem('splitmate_token');
        localStorage.removeItem('splitmate_access_token');
      }
    } catch {
      // ignore storage errors
    }
  }

  clearToken() {
    try {
      localStorage.removeItem('splitmate_token');
      localStorage.removeItem('splitmate_access_token');
    } catch {
      // ignore storage errors
    }
  }

  /**
   * Subscribe to backend availability changes.
   *
   * @param {function({isOnline: boolean}): void} callback
   * @returns {function(): void} Unsubscribe function.
   */
  subscribeStatus(callback) {
    this.onStatusChangeCallbacks.add(callback);

    if (this.isBackendAvailable !== null) {
      callback({
        isOnline: this.isBackendAvailable,
      });
    }

    return () => this.onStatusChangeCallbacks.delete(callback);
  }

  notifyStatus(isOnline) {
    if (this.isBackendAvailable !== isOnline) {
      this.isBackendAvailable = isOnline;

      this.onStatusChangeCallbacks.forEach((callback) => {
        try {
          callback({
            isOnline,
          });
        } catch (e) {
          console.error(
            '[SplitMate API] Error executing status callback:',
            e
          );
        }
      });
    }
  }

  /**
   * Check whether the backend is reachable, auto-detecting localhost vs 127.0.0.1.
   *
   * @returns {Promise<boolean>}
   */
  async checkHealth() {
    const configuredBase = this.baseURL;
    const candidates = [configuredBase];

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
        '/health',
        '/api/health',
      ]) {
        const testUrl = `${host.replace(/\/api$/, '')}${healthPath}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 2000);

        try {
          const response = await fetch(testUrl, {
            method: 'GET',
            headers: {
              Accept: 'application/json',
            },
            signal: controller.signal,
          });

          if (response.ok) {
            clearTimeout(timeoutId);

            if (host !== configuredBase) {
              console.info(
                `[SplitMate API] Auto-switching API baseURL to active host: ${host}`
              );
              this.baseURL = host;
            }

            this.notifyStatus(true);
            return true;
          }
        } catch {
          // Try next candidate
        } finally {
          clearTimeout(timeoutId);
        }
      }
    }

    this.notifyStatus(false);
    return false;
  }

  /**
   * Primary request method with error normalization, dual-host retry, and fallback.
   *
   * @param {string} endpoint - API path relative to baseURL.
   * @param {RequestInit & {isFormData?: boolean, timeout?: number, _retried?: boolean, skipAuth?: boolean}} [options={}]
   * @returns {Promise<any>}
   */
  async request(endpoint, options = {}) {
    const cleanEndpoint = endpoint.startsWith('/api/') ? endpoint.slice(4) : endpoint;
    const url = `${this.baseURL}${cleanEndpoint.startsWith('/') ? cleanEndpoint : '/' + cleanEndpoint}`;
    const isReceiptAction =
      cleanEndpoint.startsWith('/receipts/upload') ||
      cleanEndpoint.includes('/extract');

    const timeoutMs =
      options.timeout ||
      (isReceiptAction ? 90000 : DEFAULT_TIMEOUT_MS);

    const token = this.getToken();
    const headers = {
      Accept: 'application/json',
      ...(!options.isFormData && {
        'Content-Type': 'application/json',
      }),
      ...(token && !options.skipAuth ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    };

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      });

      if (!response.ok) {
        if (response.status === 401) {
          this.clearToken();
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('splitmate_auth_unauthorized'));
          }
        }

        let errorDetail = `HTTP ${response.status}: ${response.statusText}`;

        try {
          const errorJson = await response.json();
          errorDetail =
            errorJson.detail ||
            errorJson.message ||
            errorDetail;
        } catch {
          // Use default error string
        }

        const apiError = new Error(
          typeof errorDetail === 'string' ? errorDetail : JSON.stringify(errorDetail)
        );
        apiError.status = response.status;
        throw apiError;
      }

      this.notifyStatus(true);
      return await response.json();
    } catch (err) {
      clearTimeout(timeoutId);

      const isNetworkError =
        err.name === 'AbortError' ||
        err.name === 'TypeError' ||
        err.message?.toLowerCase().includes('failed to fetch') ||
        err.message?.toLowerCase().includes('fetch failed') ||
        err.message?.toLowerCase().includes('networkerror') ||
        err.message?.toLowerCase().includes('connection refused') ||
        Boolean(err.cause);

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

      // Security rule: Never mock payments or receipts
      if (
        cleanEndpoint.startsWith('/receipts/upload') ||
        cleanEndpoint.startsWith('/receipts/') ||
        cleanEndpoint.includes('/payments')
      ) {
        throw new Error(
          'Unable to connect to the backend service. Please ensure the server is running on http://localhost:8000.'
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
   * Resilient offline mock responder for core CRUD actions.
   */
  async handleMockFallback(endpoint, options = {}) {
    await new Promise((resolve) => setTimeout(resolve, 80));
    const method = (options.method || 'GET').toUpperCase();

    // 1. Health
    if (endpoint === API_ENDPOINTS.HEALTH) {
      return {
        status: 'mock_fallback',
        timestamp: new Date().toISOString(),
      };
    }

    // 2. Auth
    if (
      endpoint === API_ENDPOINTS.AUTH.CURRENT_USER ||
      endpoint === API_ENDPOINTS.AUTH.ME
    ) {
      return MOCK_USERS[0];
    }

    // 3. Groups
    if (endpoint.startsWith('/groups')) {
      if (method === 'GET') {
        if (endpoint.includes('/members')) {
          return MOCK_USERS.slice(0, 3);
        }

        return MOCK_GROUPS;
      }

      if (method === 'POST') {
        if (endpoint.includes('/members')) {
          return {
            id: `usr_mock_${Date.now()}`,
            name: 'New Member',
            email: 'member@splitmate.demo',
          };
        }

        const body = JSON.parse(options.body || '{}');

        return {
          id: `grp_mock_${Date.now()}`,
          name: body.name || 'New Group',
          created_at: new Date().toISOString(),
        };
      }
    }

    // 4. Expenses
    if (endpoint.startsWith('/expenses')) {
      if (method === 'GET') {
        if (endpoint.includes('/splits')) {
          return {
            expense_id: 'mock_expense',
            total_amount: 85.5,
            currency: 'USD',
            splits: MOCK_USERS.slice(0, 3).map((u, i) => ({
              member_id: u.id,
              member_name: u.name,
              member_email: u.email,
              amount: i === 0 ? 35.5 : 25.0,
              currency: 'USD',
            })),
          };
        }

        return MOCK_EXPENSES;
      }

      if (method === 'POST') {
        if (endpoint.includes('/assign')) {
          return {
            success: true,
            assignments_count: 3,
          };
        }

        if (endpoint.includes('/initialize-payments')) {
          return [
            {
              id: 'mock_pay_1',
              status: 'pending',
              amount: 25.0,
              currency: 'USD',
            },
          ];
        }

        const body = JSON.parse(options.body || '{}');

        return {
          id: `exp_mock_${Date.now()}`,
          group_id: body.group_id,
          total_amount: body.total_amount,
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
          amount: 25.0,
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
          amount: 25.0,
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
