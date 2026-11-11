/**
 * SplitMate API Contract & Endpoints
 * 
 * Agreed REST API contracts for FastAPI backend (Tanishq),
 * AI receipt extraction (Pawan), and PayPal Sandbox (Tanay).
 */

export const API_ENDPOINTS = {
  // Backend Health & System Status (Tanishq)
  HEALTH: '/health',

  // Authentication & User Profile (Tanishq)
  AUTH: {
    LOGIN: '/auth/login',
    REGISTER: '/auth/register',
    CURRENT_USER: '/auth/me',
    UPDATE_PROFILE: '/auth/profile',
  },

  // Groups & Members (Tanishq)
  GROUPS: {
    LIST: '/api/groups',
    CREATE: '/api/groups',
    DETAILS: (groupId) => `/api/groups/${groupId}`,
    MEMBERS: (groupId) => `/api/groups/${groupId}/members`,
    ADD_MEMBER: (groupId) => `/api/groups/${groupId}/members`,
    BALANCES: (groupId) => `/api/groups/${groupId}/balances`,
  },

  // Expense Management (Tanishq)
  EXPENSES: {
    LIST: '/api/expenses',
    CREATE: '/api/expenses',
    DETAILS: (expenseId) => `/api/expenses/${expenseId}`,
    ASSIGN: (expenseId) => `/api/expenses/${expenseId}/assign`,
    SPLITS: (expenseId) => `/api/expenses/${expenseId}/splits`,
    INITIALIZE_PAYMENTS: (expenseId) => `/api/expenses/${expenseId}/initialize-payments`,
    DELETE: (expenseId) => `/api/expenses/${expenseId}`,
    SETTLE: '/api/expenses/settle',
  },

  // AI Receipt Extraction (Pawan)
  RECEIPTS: {
    UPLOAD: '/receipts/upload',
    EXTRACT: '/receipts/extract',
    DETAILS: (receiptId) => `/receipts/${receiptId}`,
    REVIEW: (receiptId) => `/receipts/${receiptId}/review`,
    SUBMIT_EXTRACTION: (receiptId) => `/receipts/${receiptId}/extraction`,
    SAMPLE_RECEIPTS: '/receipts/samples',
  },

  // PayPal Sandbox Integration (Tanay)
  PAYMENTS: {
    CREATE_ORDER: (paymentId) => `/api/payments/${paymentId}/create-order`,
    CAPTURE: (paymentId) => `/api/payments/${paymentId}/capture`,
    GET: (paymentId) => `/api/payments/${paymentId}`,
    HISTORY: '/api/payments/history',
  },

  // Analytics & Insights (Tanishq / Dhruv)
  ANALYTICS: {
    SUMMARY: '/analytics/summary',
    CATEGORIES: '/analytics/categories',
    DEBT_GRAPH: '/analytics/debt-simplification',
  }
};
