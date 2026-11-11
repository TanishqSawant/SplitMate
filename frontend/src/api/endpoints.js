
/**
 * SplitMate API Contract & Endpoints
 *
 * Production REST API contracts for FastAPI backend,
 * AI receipt extraction, and PayPal Sandbox.
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
    INITIALIZE_PAYMENTS: (expenseId) =>
      `/expenses/${expenseId}/initialize-payments`,
  },

  // AI Receipt Extraction & Review
  RECEIPTS: {
    UPLOAD: '/receipts/upload',

    // Retrieve receipt details and poll extraction status.
    DETAILS: (receiptId) => `/receipts/${receiptId}`,
    GET: (receiptId) => `/receipts/${receiptId}`,

    // Trigger extraction and retrieve the uploaded image.
    EXTRACT: (receiptId) => `/receipts/${receiptId}/extract`,
    IMAGE: (receiptId) => `/receipts/${receiptId}/image`,

    // Update extracted receipt items.
    UPDATE_ITEMS: (receiptId) => `/receipts/${receiptId}/items`,

    // Internal backend extraction submission contract.
    SUBMIT_EXTRACTION: (receiptId) =>
      `/receipts/${receiptId}/extraction`,
  },

  // PayPal Sandbox Integration
  PAYMENTS: {
    DETAILS: (paymentId) => `/payments/${paymentId}`,
    CREATE_ORDER: (paymentId) =>
      `/payments/${paymentId}/create-order`,
    CAPTURE_ORDER: (paymentId) =>
      `/payments/${paymentId}/capture`,
    LIST_BY_EXPENSE: (expenseId) =>
      `/payments/expense/${expenseId}`,
  },

  // Analytics & Insights
  ANALYTICS: {
    SUMMARY: '/analytics/summary',
    CATEGORIES: '/analytics/categories',
    DEBT_GRAPH: '/analytics/debt-simplification',
  },
};
