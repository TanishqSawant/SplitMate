/**
 * Centralized API Endpoint Definitions for SplitMate
 *
 * All frontend requests route through these canonical paths.
 * Paths are relative to BASE_URL (http://127.0.0.1:8000/api).
 */

export const API_ENDPOINTS = {
  // System Health
  HEALTH: '/health',

  // Authentication & Users
  AUTH: {
    REGISTER: '/auth/register',
    LOGIN: '/auth/login',
    ME: '/auth/me',
    CURRENT_USER: '/auth/me',
    UPDATE_PROFILE: '/auth/profile',
    LOGOUT: '/auth/logout',
  },

  // Groups & Members
  GROUPS: {
    LIST: '/groups',
    CREATE: '/groups',
    DETAILS: (groupId) => `/groups/${groupId}`,
    ADD_MEMBER: (groupId) => `/groups/${groupId}/members`,
    MEMBERS: (groupId) => `/groups/${groupId}/members`,
    BALANCES: (groupId) => `/groups/${groupId}/balances`,
  },

  // Expense Management
  EXPENSES: {
    LIST: '/expenses',
    LIST_BY_GROUP: (groupId) => `/expenses/group/${groupId}`,
    CREATE: '/expenses',
    DETAILS: (expenseId) => `/expenses/${expenseId}`,
    ASSIGN: (expenseId) => `/expenses/${expenseId}/assign`,
    SPLITS: (expenseId) => `/expenses/${expenseId}/splits`,
    INITIALIZE_PAYMENTS: (expenseId) =>
      `/expenses/${expenseId}/initialize-payments`,
    DELETE: (expenseId) => `/expenses/${expenseId}`,
    SETTLE: '/expenses/settle',
  },

  // AI Receipt Extraction & Review
  RECEIPTS: {
    UPLOAD: '/receipts/upload',
    EXTRACT: (receiptId) => `/receipts/${receiptId}/extract`,
    DETAILS: (receiptId) => `/receipts/${receiptId}`,
    GET: (receiptId) => `/receipts/${receiptId}`,
    REVIEW: (receiptId) => `/receipts/${receiptId}/review`,
    IMAGE: (receiptId) => `/receipts/${receiptId}/image`,
    UPDATE_ITEMS: (receiptId) => `/receipts/${receiptId}/items`,
    SUBMIT_EXTRACTION: (receiptId) =>
      `/receipts/${receiptId}/extraction`,
    SAMPLE_RECEIPTS: '/receipts/samples',
  },

  // PayPal Sandbox Integration
  PAYMENTS: {
    CREATE_ORDER: (paymentId) =>
      `/payments/${paymentId}/create-order`,
    CAPTURE: (paymentId) =>
      `/payments/${paymentId}/capture`,
    CAPTURE_ORDER: (paymentId) =>
      `/payments/${paymentId}/capture`,
    DETAILS: (paymentId) => `/payments/${paymentId}`,
    GET: (paymentId) => `/payments/${paymentId}`,
    HISTORY: '/payments/history',
    LIST_BY_EXPENSE: (expenseId) =>
      `/payments/expense/${expenseId}`,
    PAYPAL_CREATE_DIRECT: '/payments/paypal/create-order',
    PAYPAL_CAPTURE_DIRECT: '/payments/paypal/capture-order',
  },

  // Analytics & Insights
  ANALYTICS: {
    SUMMARY: '/analytics/summary',
    CATEGORIES: '/analytics/categories',
  },
};
