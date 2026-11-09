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
   * Generic request executor with timeout and fallback
   */
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options.timeout || DEFAULT_TIMEOUT_MS);

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

    // 6. PayPal Create Order (Tanay's contract)
    if (endpoint === API_ENDPOINTS.PAYMENTS.CREATE_ORDER) {
      const body = JSON.parse(options.body || '{}');
      return {
        orderId: `ORDER-${Math.random().toString(36).substring(2, 11).toUpperCase()}`,
        status: 'CREATED',
        amount: body.amount,
        currency: body.currency || 'USD',
        approvalUrl: 'https://www.sandbox.paypal.com/checkoutnow?token=mock_sandbox_token'
      };
    }

    // 7. PayPal Capture Order (Tanay's contract)
    if (endpoint === API_ENDPOINTS.PAYMENTS.CAPTURE_ORDER) {
      const body = JSON.parse(options.body || '{}');
      return {
        captureId: `CAPTURE-${Math.random().toString(36).substring(2, 12).toUpperCase()}`,
        orderId: body.orderId,
        status: 'COMPLETED',
        amount: body.amount,
        payer: body.payerId,
        receiver: body.receiverEmail,
        timestamp: new Date().toISOString(),
      };
    }

    // Default fallback
    return { ok: true, message: 'Simulated mock response' };
  }
}

export const apiClient = new ApiClient();
