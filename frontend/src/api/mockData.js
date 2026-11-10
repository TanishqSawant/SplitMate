/**
 * SplitMate Mock Data Store
 * Provides rich, realistic initial state for local demo and fallback
 * when backend services are offline.
 */

export const MOCK_USERS = [
  {
    id: 'usr_dhruv',
    name: 'Dhruv Patil',
    email: 'dhruv@splitmate.io',
    avatar: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
    paypalEmail: 'dhruv-facilitator@sandbox.paypal.com',
    role: 'Frontend & UI/UX Lead',
  },
  {
    id: 'usr_tanishq',
    name: 'Tanishq Sawant',
    email: 'tanishq@splitmate.io',
    avatar: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&auto=format&fit=crop&q=80',
    paypalEmail: 'tanishq-buyer@sandbox.paypal.com',
    role: 'Backend & Database Lead',
  },
  {
    id: 'usr_pawan',
    name: 'Pawan Kumar',
    email: 'pawan@splitmate.io',
    avatar: 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&auto=format&fit=crop&q=80',
    paypalEmail: 'pawan-buyer@sandbox.paypal.com',
    role: 'AI Receipt Extraction Lead',
  },
  {
    id: 'usr_tanay',
    name: 'Tanay Gupta',
    email: 'tanay@splitmate.io',
    avatar: 'https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=150&auto=format&fit=crop&q=80',
    paypalEmail: 'tanay-sandbox@sandbox.paypal.com',
    role: 'PayPal Sandbox Integration Lead',
  },
  {
    id: 'usr_sunil',
    name: 'Sunil Verma',
    email: 'sunil@splitmate.io',
    avatar: 'https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=150&auto=format&fit=crop&q=80',
    paypalEmail: 'sunil-qa@sandbox.paypal.com',
    role: 'QA & Demo Lead',
  }
];

export const MOCK_SAMPLE_RECEIPTS = [
  {
    id: 'rcpt_bistro',
    title: 'The Italian Bistro Trattoria',
    image: 'https://images.unsplash.com/photo-1559339352-11d035aa65de?w=600&auto=format&fit=crop&q=80',
    merchant: 'The Italian Bistro Trattoria',
    date: '2026-11-06',
    category: 'Food & Dining',
    currency: 'USD',
    tax: 11.40,
    tip: 18.00,
    subtotal: 113.10,
    total: 142.50,
    confidence: 0.96,
    items: [
      { id: 'item_1', name: 'Truffle Tagliolini Pasta', quantity: 2, price: 44.00, assignedTo: ['usr_dhruv', 'usr_tanishq'] },
      { id: 'item_2', name: 'Wood-Fired Margherita Pizza', quantity: 1, price: 21.00, assignedTo: ['usr_pawan'] },
      { id: 'item_3', name: 'Pan-Seared Atlantic Salmon', quantity: 1, price: 32.00, assignedTo: ['usr_tanay'] },
      { id: 'item_4', name: 'Classic Tiramisu Dessert', quantity: 2, price: 16.10, assignedTo: ['usr_dhruv', 'usr_sunil'] },
    ]
  },
  {
    id: 'rcpt_wholefoods',
    title: 'Whole Foods Market',
    image: 'https://images.unsplash.com/photo-1578916171728-46686eac8d58?w=600&auto=format&fit=crop&q=80',
    merchant: 'Whole Foods Market #1042',
    date: '2026-11-05',
    category: 'Groceries',
    currency: 'USD',
    tax: 6.85,
    tip: 0.00,
    subtotal: 81.60,
    total: 88.45,
    confidence: 0.98,
    items: [
      { id: 'item_10', name: 'Organic Almond Milk 64oz', quantity: 2, price: 9.98, assignedTo: ['usr_dhruv', 'usr_tanishq', 'usr_tanay'] },
      { id: 'item_11', name: 'Fresh Blueberries 1lb', quantity: 2, price: 11.98, assignedTo: ['usr_pawan', 'usr_sunil'] },
      { id: 'item_12', name: 'Artisan Sourdough Loaf', quantity: 2, price: 15.00, assignedTo: ['usr_dhruv', 'usr_tanishq', 'usr_pawan', 'usr_tanay', 'usr_sunil'] },
      { id: 'item_13', name: 'Single Origin Whole Coffee Beans', quantity: 2, price: 34.00, assignedTo: ['usr_tanishq', 'usr_tanay'] },
      { id: 'item_14', name: 'Organic Avocados 4pk', quantity: 1, price: 10.64, assignedTo: ['usr_dhruv', 'usr_sunil'] }
    ]
  },
  {
    id: 'rcpt_bluebottle',
    title: 'Blue Bottle Cafe & Bakery',
    image: 'https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?w=600&auto=format&fit=crop&q=80',
    merchant: 'Blue Bottle Coffee',
    date: '2026-11-07',
    category: 'Coffee & Snacks',
    currency: 'USD',
    tax: 1.80,
    tip: 3.00,
    subtotal: 20.00,
    total: 24.80,
    confidence: 0.99,
    items: [
      { id: 'item_20', name: 'New Orleans Cold Brew', quantity: 2, price: 12.00, assignedTo: ['usr_dhruv', 'usr_tanay'] },
      { id: 'item_21', name: 'Warm Almond Croissant', quantity: 2, price: 8.00, assignedTo: ['usr_tanishq', 'usr_pawan'] }
    ]
  }
];

export const MOCK_GROUPS = [
  {
    id: 'grp_hackathon',
    name: 'PayPal AI Hackathon Squad',
    description: 'Shared expenses for the hackathon weekend, team dinners, and API credits.',
    category: 'Project',
    currency: 'USD',
    createdAt: '2026-11-01',
    members: [
      { userId: 'usr_dhruv', role: 'Admin' },
      { userId: 'usr_tanishq', role: 'Member' },
      { userId: 'usr_pawan', role: 'Member' },
      { userId: 'usr_tanay', role: 'Member' },
      { userId: 'usr_sunil', role: 'Member' }
    ],
    totalExpenses: 468.25,
    userBalance: 64.50, // Positive: you are owed; Negative: you owe
  },
  {
    id: 'grp_tech_summit',
    name: 'San Jose Tech Summit Trip',
    description: 'Hotel bookings, rides, flights, and conference catering.',
    category: 'Travel',
    currency: 'USD',
    createdAt: '2026-10-20',
    members: [
      { userId: 'usr_dhruv', role: 'Admin' },
      { userId: 'usr_tanishq', role: 'Member' },
      { userId: 'usr_tanay', role: 'Member' }
    ],
    totalExpenses: 1140.00,
    userBalance: -45.00,
  },
  {
    id: 'grp_apt402',
    name: 'Apartment 402 Utilities',
    description: 'Gigabit fiber Wi-Fi, electricity, groceries, and home maintenance.',
    category: 'Housing',
    currency: 'USD',
    createdAt: '2026-09-01',
    members: [
      { userId: 'usr_dhruv', role: 'Admin' },
      { userId: 'usr_pawan', role: 'Member' },
      { userId: 'usr_sunil', role: 'Member' }
    ],
    totalExpenses: 520.80,
    userBalance: 82.20,
  }
];

export const MOCK_EXPENSES = [
  {
    id: 'exp_001',
    groupId: 'grp_hackathon',
    description: 'Team Kickoff Dinner at Bistro',
    amount: 142.50,
    currency: 'USD',
    category: 'Food & Dining',
    paidBy: 'usr_dhruv',
    date: '2026-11-06',
    receiptId: 'rcpt_bistro',
    splitType: 'ITEMIZED',
    splitDetails: [
      { userId: 'usr_dhruv', share: 36.50, isPaid: true },
      { userId: 'usr_tanishq', share: 29.50, isPaid: false },
      { userId: 'usr_pawan', share: 28.50, isPaid: false },
      { userId: 'usr_tanay', share: 38.00, isPaid: false },
      { userId: 'usr_sunil', share: 10.00, isPaid: true },
    ]
  },
  {
    id: 'exp_002',
    groupId: 'grp_hackathon',
    description: 'Hackathon Grocery & Energy Drinks',
    amount: 88.45,
    currency: 'USD',
    category: 'Groceries',
    paidBy: 'usr_tanishq',
    date: '2026-11-05',
    receiptId: 'rcpt_wholefoods',
    splitType: 'EQUAL',
    splitDetails: [
      { userId: 'usr_dhruv', share: 17.69, isPaid: false },
      { userId: 'usr_tanishq', share: 17.69, isPaid: true },
      { userId: 'usr_pawan', share: 17.69, isPaid: true },
      { userId: 'usr_tanay', share: 17.69, isPaid: false },
      { userId: 'usr_sunil', share: 17.69, isPaid: false },
    ]
  },
  {
    id: 'exp_003',
    groupId: 'grp_hackathon',
    description: 'Afternoon Brainstorm Coffee & Pastries',
    amount: 24.80,
    currency: 'USD',
    category: 'Coffee & Snacks',
    paidBy: 'usr_tanay',
    date: '2026-11-07',
    receiptId: 'rcpt_bluebottle',
    splitType: 'ITEMIZED',
    splitDetails: [
      { userId: 'usr_dhruv', share: 6.20, isPaid: true },
      { userId: 'usr_tanishq', share: 6.20, isPaid: false },
      { userId: 'usr_pawan', share: 6.20, isPaid: false },
      { userId: 'usr_tanay', share: 6.20, isPaid: true },
    ]
  },
  {
    id: 'exp_004',
    groupId: 'grp_tech_summit',
    description: 'Airport Ride to San Jose Convention Center',
    amount: 62.00,
    currency: 'USD',
    category: 'Travel',
    paidBy: 'usr_tanay',
    date: '2026-10-21',
    receiptId: null,
    splitType: 'EQUAL',
    splitDetails: [
      { userId: 'usr_dhruv', share: 20.66, isPaid: false },
      { userId: 'usr_tanishq', share: 20.67, isPaid: true },
      { userId: 'usr_tanay', share: 20.67, isPaid: true },
    ]
  },
  {
    id: 'exp_005',
    groupId: 'grp_apt402',
    description: 'High-Speed Fiber Internet Bill',
    amount: 90.00,
    currency: 'USD',
    category: 'Utilities',
    paidBy: 'usr_dhruv',
    date: '2026-11-02',
    receiptId: null,
    splitType: 'EQUAL',
    splitDetails: [
      { userId: 'usr_dhruv', share: 30.00, isPaid: true },
      { userId: 'usr_pawan', share: 30.00, isPaid: false },
      { userId: 'usr_sunil', share: 30.00, isPaid: false },
    ]
  }
];

export const MOCK_PAYPAL_TRANSACTIONS = [
  {
    id: 'txn_pp_901',
    orderId: 'ORDER-7KA982319082',
    captureId: 'CAPTURE-48B9238914',
    payerId: 'usr_tanishq',
    payerName: 'Tanishq Sawant',
    receiverId: 'usr_dhruv',
    receiverName: 'Dhruv Patil',
    receiverEmail: 'dhruv-facilitator@sandbox.paypal.com',
    amount: 32.50,
    currency: 'USD',
    date: '2026-11-06T19:42:10Z',
    status: 'COMPLETED',
    note: 'Settled Bistro Dinner Share',
    method: 'PayPal Sandbox Balance'
  },
  {
    id: 'txn_pp_902',
    orderId: 'ORDER-3XN451920381',
    captureId: 'CAPTURE-19P5402914',
    payerId: 'usr_dhruv',
    payerName: 'Dhruv Patil',
    receiverId: 'usr_tanay',
    receiverName: 'Tanay Gupta',
    receiverEmail: 'tanay-sandbox@sandbox.paypal.com',
    amount: 25.00,
    currency: 'USD',
    date: '2026-11-04T14:15:30Z',
    status: 'COMPLETED',
    note: 'Settle Airport Uber Cab',
    method: 'PayPal Sandbox (Linked Bank)'
  }
];

