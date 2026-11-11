/**
 * SplitMate API Contract & Endpoints
 * 
 * Production REST API contracts for FastAPI backend (Tanishq),
 * AI receipt extraction (Pawan), and PayPal Sandbox (Tanay).
 */

export const API_ENDPOINTS = {
  // Backend Health & System Status
  HEALTH: '/health',

  // Authentication & User Profile
  AUTH: {
    LOGIN: '/auth/login',
    REGISTER: '/auth/register',
    CURRENT_USER: '/auth/me',
    UPDATE_PROFILE: '/auth/profile',
  },

  // Groups & Members
  GROUPS: {
    LIST: '/groups',
    CREATE: '/groups',
    DETAILS: (groupId) => `/groups/${groupId}`,
    ADD_MEMBER: (groupId) => `/groups/${groupId}/members`,
    MEMBERS: (groupId) => `/groups/${groupId}/members`,
  },

  // Expense Management
  EXPENSES: {
    LIST: '/expenses',
    LIST_BY_GROUP: (groupId) => `/expenses/group/${groupId}`,
    CREATE: '/expenses',
    DETAILS: (expenseId) => `/expenses/${expenseId}`,
    ASSIGN: (expenseId) => `/expenses/${expenseId}/assign`,
    SPLITS: (expenseId) => `/expenses/${expenseId}/splits`,
    INITIALIZE_PAYMENTS: (expenseId) => `/expenses/${expenseId}/initialize-payments`,
  },

  // AI Receipt Extraction & Review
  RECEIPTS: {
    UPLOAD: '/receipts/upload',
    DETAILS: (receiptId) => `/receipts/${receiptId}`,
    EXTRACT: (receiptId) => `/receipts/${receiptId}/extract`,
    IMAGE: (receiptId) => `/receipts/${receiptId}/image`,
    UPDATE_ITEMS: (receiptId) => `/receipts/${receiptId}/items`,
    SUBMIT_EXTRACTION: (receiptId) => `/receipts/${receiptId}/extraction`,
    SAMPLE_RECEIPTS: '/receipts/samples',
  },

  // PayPal Sandbox Integration
  PAYMENTS: {
    DETAILS: (paymentId) => `/payments/${paymentId}`,
    CREATE_ORDER: (paymentId) => `/payments/${paymentId}/create-order`,
    CAPTURE_ORDER: (paymentId) => `/payments/${paymentId}/capture`,
    LIST_BY_EXPENSE: (expenseId) => `/payments/expense/${expenseId}`,
  },

  // Analytics & Insights
  ANALYTICS: {
    SUMMARY: '/analytics/summary',
    CATEGORIES: '/analytics/categories',
    DEBT_GRAPH: '/analytics/debt-simplification',
  }
};
