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
    LIST: '/groups',
    CREATE: '/groups',
    DETAILS: (groupId) => `/groups/${groupId}`,
    ADD_MEMBER: (groupId) => `/groups/${groupId}/members`,
    BALANCES: (groupId) => `/groups/${groupId}/balances`,
  },

  // Expense Management (Tanishq)
  EXPENSES: {
    LIST: '/expenses',
    CREATE: '/expenses',
    DETAILS: (expenseId) => `/expenses/${expenseId}`,
    DELETE: (expenseId) => `/expenses/${expenseId}`,
    SETTLE: '/expenses/settle',
  },

  // AI Receipt Extraction (Pawan)
  RECEIPTS: {
    EXTRACT: '/receipts/extract',
    SAMPLE_RECEIPTS: '/receipts/samples',
  },

  // PayPal Sandbox Integration (Tanay)
  PAYMENTS: {
    CREATE_ORDER: '/payments/paypal/create-order',
    CAPTURE_ORDER: '/payments/paypal/capture-order',
    HISTORY: '/payments/history',
  },

  // Analytics & Insights (Tanishq / Dhruv)
  ANALYTICS: {
    SUMMARY: '/analytics/summary',
    CATEGORIES: '/analytics/categories',
    DEBT_GRAPH: '/analytics/debt-simplification',
  }
};

