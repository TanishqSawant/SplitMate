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
    ASSIGN: (expenseId) => `/expenses/${expenseId}/assign`,
    SPLITS: (expenseId) => `/expenses/${expenseId}/splits`,
    INITIALIZE_PAYMENTS: (expenseId) => `/expenses/${expenseId}/initialize-payments`,
  },

  // AI Receipt Extraction (Pawan + Tanishq)
  // Backend contract (receipts.py):
  //   POST /api/receipts/upload           → upload file, returns {id, extraction_status: 'PENDING'}
  //   GET  /api/receipts/{receipt_id}     → poll status; extraction_status becomes 'COMPLETED' once Pawan's AI service processes it
  //   POST /api/receipts/{receipt_id}/extraction → Pawan's AI service submits results (internal, not called by frontend)
  RECEIPTS: {
    UPLOAD: '/receipts/upload',
    GET: (receiptId) => `/receipts/${receiptId}`,
    SUBMIT_EXTRACTION: (receiptId) => `/receipts/${receiptId}/extraction`,
  },

  // PayPal Sandbox Integration (Tanay & Dhruv - Phase 9)
  // Backend contract (payments.py):
  //   POST /api/payments/{payment_id}/create-order  → creates PayPal order (status: pending -> order_created)
  //   POST /api/payments/{payment_id}/capture       → captures order server-side (status: order_created -> captured)
  //   GET  /api/payments/{payment_id}               → checks verified status
  PAYMENTS: {
    CREATE_ORDER: (paymentId) => `/payments/${paymentId}/create-order`,
    CAPTURE: (paymentId) => `/payments/${paymentId}/capture`,
    GET: (paymentId) => `/payments/${paymentId}`,
    HISTORY: '/payments/history',
  },

  // Analytics & Insights (Tanishq / Dhruv)
  ANALYTICS: {
    SUMMARY: '/analytics/summary',
    CATEGORIES: '/analytics/categories',
    DEBT_GRAPH: '/analytics/debt-simplification',
  }
};

