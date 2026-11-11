import React, { createContext, useContext, useState, useMemo } from 'react';
import {
  MOCK_GROUPS,
  MOCK_EXPENSES,
  MOCK_PAYPAL_TRANSACTIONS,
  MOCK_SAMPLE_RECEIPTS,
  MOCK_USERS
} from '../api/mockData';
import { apiClient } from '../api/client';
import { API_ENDPOINTS } from '../api/endpoints';
import { useAuth } from './AuthContext';
import confetti from 'canvas-confetti';

const ExpenseContext = createContext();

export function ExpenseProvider({ children }) {
  const { currentUser } = useAuth();
  const [groups, setGroups] = useState(MOCK_GROUPS);
  const [expenses, setExpenses] = useState(MOCK_EXPENSES);
  const [transactions, setTransactions] = useState(MOCK_PAYPAL_TRANSACTIONS);
  const [activeGroup, setActiveGroup] = useState(MOCK_GROUPS[0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Active receipt scan session
  const [receiptScan, setReceiptScan] = useState({
    status: 'idle', // 'idle' | 'uploading' | 'processing' | 'pending' | 'review' | 'error'
    // 'pending' = file uploaded to backend, waiting for Pawan's AI service to POST results (polling timed out)
    file: null,
    previewUrl: null,
    progress: 0,
    stage: '',
    extractedData: null,
    confidence: null,
    error: null,
    warnings: [],
    editedFields: {},
    receiptId: null, // UUID returned by POST /api/receipts/upload
  });

  // Active PayPal settlement modal state
  const [payPalModal, setPayPalModal] = useState({
    isOpen: false,
    payer: null,
    receiver: null,
    amount: 0,
    currency: 'USD',
    note: '',
    groupId: null,
    status: 'idle', // 'idle' | 'initiating' | 'authorizing' | 'capturing' | 'success' | 'error'
    transactionId: null,
  });

  // Calculate user's overall financial summary
  const summary = useMemo(() => {
    if (!currentUser) return { totalOwedToYou: 0, totalYouOwe: 0, netBalance: 0 };

    let totalOwedToYou = 0;
    let totalYouOwe = 0;

    expenses.forEach((expense) => {
      const isPaidByMe = expense.paidBy === currentUser.id;

      if (expense.splitDetails && expense.splitDetails.length > 0) {
        expense.splitDetails.forEach((detail) => {
          if (isPaidByMe && detail.userId !== currentUser.id && !detail.isPaid) {
            totalOwedToYou += detail.share;
          } else if (!isPaidByMe && detail.userId === currentUser.id && !detail.isPaid) {
            totalYouOwe += detail.share;
          }
        });
      }
    });

    return {
      totalOwedToYou: Number(totalOwedToYou.toFixed(2)),
      totalYouOwe: Number(totalYouOwe.toFixed(2)),
      netBalance: Number((totalOwedToYou - totalYouOwe).toFixed(2)),
    };
  }, [expenses, currentUser]);

  // Compute who owes whom in each group / across all groups
  const debtBreakdown = useMemo(() => {
    if (!currentUser) return [];

    const debtsMap = new Map();

    expenses.forEach((expense) => {
      const payerId = expense.paidBy;
      if (!expense.splitDetails) return;

      expense.splitDetails.forEach((split) => {
        if (split.userId === payerId || split.isPaid) return;

        // split.userId owes payerId the split.share
        const debtor = split.userId;
        const creditor = payerId;
        const amount = split.share;

        const key = `${debtor}->${creditor}`;
        const reverseKey = `${creditor}->${debtor}`;

        if (debtsMap.has(reverseKey)) {
          const existing = debtsMap.get(reverseKey);
          if (existing >= amount) {
            debtsMap.set(reverseKey, existing - amount);
          } else {
            debtsMap.delete(reverseKey);
            debtsMap.set(key, amount - existing);
          }
        } else {
          debtsMap.set(key, (debtsMap.get(key) || 0) + amount);
        }
      });
    });

    const result = [];
    debtsMap.forEach((amt, key) => {
      if (amt <= 0.01) return;
      const [debtorId, creditorId] = key.split('->');
      const debtor = MOCK_USERS.find((u) => u.id === debtorId) || { id: debtorId, name: 'User' };
      const creditor = MOCK_USERS.find((u) => u.id === creditorId) || { id: creditorId, name: 'User' };

      result.push({
        id: key,
        debtor,
        creditor,
        amount: Number(amt.toFixed(2)),
        isCurrentUserDebtor: debtorId === currentUser.id,
        isCurrentUserCreditor: creditorId === currentUser.id,
      });
    });

    return result;
  }, [expenses, currentUser]);

  // Create Group
  const createGroup = async (groupData) => {
    setLoading(true);
    try {
      const response = await apiClient.request(API_ENDPOINTS.GROUPS.CREATE, {
        method: 'POST',
        body: JSON.stringify(groupData),
      });
      setGroups((prev) => [response, ...prev]);
      setActiveGroup(response);
      return { success: true, group: response };
    } catch (err) {
      setError(err.message);
      return { success: false, error: err.message };
    } finally {
      setLoading(false);
    }
  };

  // Add Expense
  const addExpense = async (expenseData) => {
    setLoading(true);
    try {
      const response = await apiClient.request(API_ENDPOINTS.EXPENSES.CREATE, {
        method: 'POST',
        body: JSON.stringify(expenseData),
      });
      setExpenses((prev) => [response, ...prev]);
      return { success: true, expense: response };
    } catch (err) {
      return { success: false, error: err.message };
    } finally {
      setLoading(false);
    }
  };

  // Reset Receipt Scanner to clean state
  const resetReceiptScan = () => {
    if (receiptScan.previewUrl && receiptScan.previewUrl.startsWith('blob:')) {
      try {
        URL.revokeObjectURL(receiptScan.previewUrl);
      } catch {
        // ignore revoke error
      }
    }
    setReceiptScan({
      status: 'idle',
      file: null,
      previewUrl: null,
      progress: 0,
      stage: '',
      extractedData: null,
      confidence: null,
      error: null,
      warnings: [],
      editedFields: {},
      receiptId: null,
    });
  };

  // Start Receipt Extraction using the real backend contract:
  //   Step 1: POST /api/receipts/upload  → returns {id, extraction_status: 'PENDING', ...}
  //   Step 2: Poll GET /api/receipts/{id} until extraction_status === 'COMPLETED'
  //            (Pawan's AI service calls POST /api/receipts/{id}/extraction when done)
  //   Step 3: Map completed ReceiptResponse into extractedData state
  const processReceiptFile = async (file) => {
    // 1. Prevent duplicate concurrent submissions
    if (receiptScan.status === 'uploading' || receiptScan.status === 'processing') {
      return;
    }

    // 2. Validate file existence and format
    if (!file) return;

    const allowedExtensions = ['.jpg', '.jpeg', '.png', '.webp', '.pdf'];
    const fileName = file.name || '';
    const fileExt = fileName.substring(fileName.lastIndexOf('.')).toLowerCase();
    const isAllowedExt = allowedExtensions.includes(fileExt);
    const isAllowedMime = file.type?.startsWith('image/') || file.type === 'application/pdf';

    if (!isAllowedExt && !isAllowedMime) {
      setReceiptScan({
        status: 'error',
        file: null,
        previewUrl: null,
        progress: 0,
        stage: '',
        extractedData: null,
        confidence: null,
        error: "File format not supported. Please upload a JPG, JPEG, PNG, WEBP, or PDF receipt.",
        warnings: [],
        editedFields: {},
      });
      return;
    }

    // 3. Validate size bound (10 MB maximum, matching backend config)
    const MAX_SIZE_BYTES = 10 * 1024 * 1024;
    if (file.size > MAX_SIZE_BYTES) {
      setReceiptScan({
        status: 'error',
        file: null,
        previewUrl: null,
        progress: 0,
        stage: '',
        extractedData: null,
        confidence: null,
        error: `File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds the 10 MB limit. Please upload a smaller image.`,
        warnings: [],
        editedFields: {},
      });
      return;
    }

    // 4. Clean previous session and allocate object URL
    if (receiptScan.previewUrl && receiptScan.previewUrl.startsWith('blob:')) {
      try {
        URL.revokeObjectURL(receiptScan.previewUrl);
      } catch {
        // ignore revoke error
      }
    }
    const previewUrl = URL.createObjectURL(file);

    // --- STEP 1: Upload ---
    setReceiptScan({
      status: 'uploading',
      file,
      previewUrl,
      progress: 15,
      stage: 'Uploading receipt to server...',
      extractedData: null,
      confidence: null,
      error: null,
      warnings: [],
      editedFields: {},
    });

    try {
      // Build strictly compliant FormData — do NOT set Content-Type manually
      const formData = new FormData();
      formData.append('file', file);

      // POST /api/receipts/upload returns {id, extraction_status: 'PENDING', ...}
      const uploadResponse = await apiClient.request(API_ENDPOINTS.RECEIPTS.UPLOAD, {
        method: 'POST',
        body: formData,
        isFormData: true,
        timeout: 15000, // 15s for file upload
      });

      if (!uploadResponse || !uploadResponse.id) {
        throw new Error("Receipt upload failed. The server did not return a receipt ID.");
      }

      const receiptId = uploadResponse.id;

      // --- STEP 2: Poll for extraction completion ---
      setReceiptScan((prev) => ({
        ...prev,
        status: 'processing',
        progress: 35,
        stage: 'Analyzing your receipt...',
      }));

      const POLL_INTERVAL_MS = 2000;
      const MAX_POLL_ATTEMPTS = 30; // 30 × 2s = 60s max wait
      const STAGE_LABELS = [
        { threshold: 40, label: 'Analyzing your receipt...' },
        { threshold: 55, label: 'Extracting merchant details...' },
        { threshold: 70, label: 'Identifying individual items...' },
        { threshold: 85, label: 'Calculating taxes and totals...' },
        { threshold: 95, label: 'Finalizing extraction results...' },
      ];

      let pollAttempt = 0;
      let receiptData = null;

      while (pollAttempt < MAX_POLL_ATTEMPTS) {
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        pollAttempt++;

        // Calculate smooth progress: 35% → 95% across max attempts
        const rawProgress = 35 + Math.round((pollAttempt / MAX_POLL_ATTEMPTS) * 60);
        const cappedProgress = Math.min(rawProgress, 95);
        const stageLabel = STAGE_LABELS.findLast?.((s) => cappedProgress >= s.threshold)?.label
          ?? STAGE_LABELS[Math.min(pollAttempt - 1, STAGE_LABELS.length - 1)].label;

        setReceiptScan((prev) => ({
          ...prev,
          progress: cappedProgress,
          stage: stageLabel,
        }));

        // GET /api/receipts/{id}
        let pollData;
        try {
          pollData = await apiClient.request(API_ENDPOINTS.RECEIPTS.GET(receiptId), {
            method: 'GET',
            timeout: 8000,
          });
        } catch {
          // Network error during poll — propagate
          throw new Error(`Unable to connect to the receipt extraction service.`);
        }

        if (pollData.extraction_status === 'COMPLETED') {
          receiptData = pollData;
          break;
        }

        if (pollData.extraction_status === 'FAILED') {
          throw new Error("Receipt extraction failed. Please try again.");
        }

        // Still PENDING — continue polling
      }

      if (!receiptData) {
        // Timed out — AI service may still be processing
        setReceiptScan((prev) => ({
          ...prev,
          status: 'pending',
          progress: 95,
          stage: 'AI extraction is still processing...',
          receiptId,
        }));
        return;
      }

      // --- STEP 3: Map ReceiptResponse into frontend extractedData ---
      // Backend ReceiptResponse: { id, merchant_name, currency, subtotal, tax, total, extraction_status, items[] }
      // items[]: { id, receipt_id, item_name, quantity, unit_price, total_price }

      const rawItems = Array.isArray(receiptData.items) ? receiptData.items : [];
      const formattedItems = rawItems.map((item, idx) => ({
        id: item.id || `item_${idx + 1}`,
        name: item.item_name || 'Unnamed Item',
        quantity: item.quantity != null ? Number(item.quantity) : 1,
        price: Number(item.total_price ?? item.unit_price ?? 0),
        unitPrice: item.unit_price != null ? Number(item.unit_price) : null,
      }));

      const merchant = receiptData.merchant_name || null;
      const totalAmount = receiptData.total != null ? Number(receiptData.total) : null;
      const subtotalVal = receiptData.subtotal != null ? Number(receiptData.subtotal) : null;
      const taxVal = receiptData.tax != null ? Number(receiptData.tax) : null;

      // Assign items to active group members
      const defaultMembers = activeGroup?.members?.map((m) => m.userId) || [currentUser?.id].filter(Boolean);
      const itemsWithAssignments = formattedItems.map((item) => ({
        ...item,
        assignedTo: [...defaultMembers],
      }));

      // Compute finalTotal: use backend total, or derive from subtotal+tax
      const computedTotal = (subtotalVal || 0) + (taxVal || 0);
      const finalTotal = totalAmount != null && totalAmount > 0 ? totalAmount : computedTotal;

      // Math consistency warning
      const warnings = [];
      if (subtotalVal !== null && taxVal !== null && totalAmount !== null) {
        const expectedTotal = Number((subtotalVal + taxVal).toFixed(2));
        if (Math.abs(totalAmount - expectedTotal) > 0.05) {
          warnings.push(`Mathematical discrepancy: Subtotal ($${subtotalVal.toFixed(2)}) + Tax ($${taxVal.toFixed(2)}) = $${expectedTotal.toFixed(2)}, but receipt total is $${totalAmount.toFixed(2)}. Please verify.`);
        }
      }

      setReceiptScan({
        status: 'review',
        file,
        previewUrl,
        progress: 100,
        stage: 'Extraction complete',
        receiptId,
        extractedData: {
          merchant,
          date: null,
          category: 'General',
          currency: receiptData.currency || 'USD',
          subtotal: subtotalVal,
          tax: taxVal,
          tip: null,
          total: finalTotal,
          items: itemsWithAssignments,
        },
        // Confidence not included in ReceiptResponse — Pawan's service tracks it internally
        confidence: null,
        warnings,
        editedFields: {},
        error: null,
      });

    } catch (err) {
      const msg = err.message || '';
      let userFriendlyError = "Receipt extraction failed. Please try again.";

      if (
        msg.toLowerCase().includes('unable to connect') ||
        msg.toLowerCase().includes('unreachable') ||
        msg.toLowerCase().includes('failed to fetch') ||
        msg.toLowerCase().includes('network') ||
        msg.toLowerCase().includes('econnrefused')
      ) {
        userFriendlyError = "Unable to connect to the receipt extraction service.";
      } else if (
        msg.toLowerCase().includes('not appear to contain') ||
        msg.toLowerCase().includes('not a receipt') ||
        msg.toLowerCase().includes('invalid image') ||
        msg.toLowerCase().includes('400')
      ) {
        userFriendlyError = "This image does not appear to contain a valid receipt.";
      } else if (
        msg.toLowerCase().includes('blur') ||
        msg.toLowerCase().includes('quality')
      ) {
        userFriendlyError = "We couldn't read this receipt clearly. Please upload a higher-quality image.";
      } else if (
        msg.toLowerCase().includes('413') ||
        msg.toLowerCase().includes('too large')
      ) {
        userFriendlyError = "The file is too large. Please upload an image under 10 MB.";
      } else if (
        msg.toLowerCase().includes('422') ||
        msg.toLowerCase().includes('unprocessable')
      ) {
        userFriendlyError = "The file could not be processed by the server. Please check the format and try again.";
      } else if (
        msg.toLowerCase().includes('500') ||
        msg.toLowerCase().includes('internal server') ||
        msg.toLowerCase().includes('json') ||
        msg.toLowerCase().includes('syntaxerror')
      ) {
        userFriendlyError = "Receipt extraction failed. Please try again.";
      } else if (msg) {
        userFriendlyError = msg;
      }

      setReceiptScan((prev) => ({
        ...prev,
        status: 'error',
        error: userFriendlyError,
        extractedData: null,
      }));
    }
  };

  // Load Sample Receipt for one-click demo
  const loadSampleReceipt = (sampleId) => {
    const sample = MOCK_SAMPLE_RECEIPTS.find((s) => s.id === sampleId) || MOCK_SAMPLE_RECEIPTS[0];
    setReceiptScan({
      status: 'review',
      file: null,
      previewUrl: sample.image,
      progress: 100,
      stage: 'Loaded demo benchmark sample',
      extractedData: {
        merchant: sample.merchant,
        date: sample.date,
        category: sample.category,
        currency: sample.currency,
        tax: sample.tax,
        tip: sample.tip,
        subtotal: sample.subtotal,
        total: sample.total,
        confidence: sample.confidence,
        items: JSON.parse(JSON.stringify(sample.items)),
      },
      confidence: sample.confidence,
      warnings: [],
      editedFields: {},
      error: null,
    });
  };

  // Update item assignment in scanned receipt
  const updateItemAssignment = (itemId, userIds) => {
    setReceiptScan((prev) => {
      if (!prev.extractedData) return prev;
      const updatedItems = prev.extractedData.items.map((item) => {
        if (item.id === itemId) {
          return { ...item, assignedTo: userIds };
        }
        return item;
      });
      return {
        ...prev,
        extractedData: {
          ...prev.extractedData,
          items: updatedItems,
        },
      };
    });
  };

  // Update item line details (quantity, price, name)
  const updateExtractedItem = (itemId, updates) => {
    setReceiptScan((prev) => {
      if (!prev.extractedData) return prev;
      const updatedItems = prev.extractedData.items.map((item) => {
        if (item.id === itemId) {
          return { ...item, ...updates, isEdited: true };
        }
        return item;
      });
      const newSubtotal = Number(updatedItems.reduce((sum, it) => sum + (it.price || 0), 0).toFixed(2));
      const tax = prev.extractedData.tax || 0;
      const tip = prev.extractedData.tip || 0;
      const newTotal = Number((newSubtotal + tax + tip).toFixed(2));

      return {
        ...prev,
        extractedData: {
          ...prev.extractedData,
          items: updatedItems,
          subtotal: newSubtotal,
          total: newTotal,
        },
        editedFields: {
          ...prev.editedFields,
          items: true,
          subtotal: true,
          total: true,
        },
      };
    });
  };

  // Update receipt line items or metadata
  const updateReceiptMetadata = (field, value) => {
    setReceiptScan((prev) => {
      if (!prev.extractedData) return prev;
      return {
        ...prev,
        extractedData: {
          ...prev.extractedData,
          [field]: value,
        },
        editedFields: {
          ...prev.editedFields,
          [field]: true,
        },
      };
    });
  };

  // Finalize receipt scan into an expense
  const finalizeReceiptScan = async (targetGroupId, paidByUserId) => {
    if (!receiptScan.extractedData) return;

    const data = receiptScan.extractedData;
    const targetGroup = groups.find((g) => g.id === targetGroupId) || activeGroup;
    const groupMemberIds = targetGroup?.members?.map((m) => m.userId) || [currentUser.id];

    // Compute shares based on item assignments + tax/tip proportional split
    const userShares = {};
    groupMemberIds.forEach((id) => (userShares[id] = 0));

    let itemsTotal = 0;
    data.items.forEach((item) => {
      itemsTotal += item.price;
      const assigned = item.assignedTo && item.assignedTo.length > 0 ? item.assignedTo : groupMemberIds;
      const sharePerUser = item.price / assigned.length;
      assigned.forEach((uId) => {
        userShares[uId] = (userShares[uId] || 0) + sharePerUser;
      });
    });

    // Pro-rate tax and tip based on items share
    const extraCharges = (data.tax || 0) + (data.tip || 0);
    if (extraCharges > 0 && itemsTotal > 0) {
      groupMemberIds.forEach((uId) => {
        const userItemRatio = (userShares[uId] || 0) / itemsTotal;
        userShares[uId] = (userShares[uId] || 0) + extraCharges * userItemRatio;
      });
    }

    const splitDetails = groupMemberIds.map((uId) => ({
      userId: uId,
      share: Number((userShares[uId] || 0).toFixed(2)),
      isPaid: uId === paidByUserId,
    }));

    const newExpense = {
      id: `exp_${Date.now()}`,
      groupId: targetGroupId,
      description: `${data.merchant} (AI Receipt Split)`,
      amount: data.total,
      currency: data.currency || 'USD',
      category: data.category || 'Food & Dining',
      paidBy: paidByUserId || currentUser.id,
      date: data.date || new Date().toISOString().split('T')[0],
      receiptId: `rcpt_${Date.now()}`,
      splitType: 'ITEMIZED',
      splitDetails,
    };

    setExpenses((prev) => [newExpense, ...prev]);

    // Reset scan state
    setReceiptScan({
      status: 'idle',
      file: null,
      previewUrl: null,
      progress: 0,
      extractedData: null,
      confidence: null,
      error: null,
    });

    confetti({
      particleCount: 80,
      spread: 70,
      origin: { y: 0.6 }
    });

    return newExpense;
  };

  // Open PayPal Payment Modal for a debt
  const openPayPalPayment = async ({
    creditor,
    debtor,
    amount,
    note,
    groupId,
    expenseId,
    paymentId,
    payerMemberId,
  }) => {
    let resolvedPaymentId = paymentId || null;

    // If expenseId provided but no paymentId, initialize payments with backend
    if (expenseId && !resolvedPaymentId) {
      const initResult = await initializeExpensePayments(expenseId);
      if (initResult.success && Array.isArray(initResult.payments)) {
        const myPayment = initResult.payments.find(
          (p) => p.member_id === (payerMemberId || debtor?.id || currentUser?.id)
        ) || initResult.payments[0];
        if (myPayment) {
          resolvedPaymentId = myPayment.id;
        }
      }
    }

    setPayPalModal({
      isOpen: true,
      payer: debtor || currentUser,
      receiver: creditor,
      amount,
      currency: 'USD',
      note: note || `Settle debt with ${creditor?.name || 'creditor'}`,
      groupId,
      expenseId: expenseId || null,
      paymentId: resolvedPaymentId,
      payerMemberId: payerMemberId || null,
      status: 'idle',
      transactionId: null,
      error: null,
    });
  };

  const closePayPalModal = () => {
    setPayPalModal((prev) => ({ ...prev, isOpen: false, status: 'idle', error: null }));
  };

<<<<<<< HEAD
  // Execute PayPal Payment Flow (Tanay's integration)
  const executePayPalPayment = async () => {
    // Prevent duplicate simultaneous submissions
    if (payPalModal.status !== 'idle' && payPalModal.status !== 'error') return;

    setPayPalModal((prev) => ({ ...prev, status: 'initiating', error: null }));

=======
  // Fetch real payment history from backend (Tanay's GET /api/payments/history)
  const fetchPaymentHistory = async () => {
>>>>>>> feature/paypal-sandbox
    try {
      const payments = await apiClient.request(API_ENDPOINTS.PAYMENTS.HISTORY, {
        method: 'GET',
      });
      if (Array.isArray(payments)) {
        const normalized = payments.map((p) => ({
          id: p.id,
          orderId: p.paypal_order_id,
          captureId: p.paypal_capture_id || p.id,
          payerId: p.member_id,
          payerName: p.member_id ? `Member (${String(p.member_id).substring(0, 8)})` : 'Squad Member',
          receiverName: 'SplitMate Group',
          amount: parseFloat(p.amount) || 0,
          currency: p.currency || 'USD',
          date: p.updated_at || p.created_at,
          status: (p.status || '').toUpperCase(),
          raw: p,
        }));
        setTransactions(normalized);
        return { success: true, transactions: normalized };
      }
    } catch (err) {
      console.warn('[SplitMate] Failed to fetch payment history from backend:', err.message);
    }
  };

  // Fetch payment history on mount and when currentUser changes
  useEffect(() => {
    fetchPaymentHistory();
  }, [currentUser]);

  // Initialize expense payments after splits are finalized (POST /api/expenses/{expense_id}/initialize-payments)
  const initializeExpensePayments = async (expenseId) => {
    if (!expenseId) return { success: false, error: 'No expense ID provided' };
    try {
      const payments = await apiClient.request(
        API_ENDPOINTS.EXPENSES.INITIALIZE_PAYMENTS(expenseId),
        { method: 'POST' }
      );
      return { success: true, payments };
    } catch (err) {
      console.warn(`[SplitMate] initialize-payments failed for ${expenseId}:`, err.message);
      return { success: false, error: err.message };
    }
  };

  // Step 1: Create PayPal Order via FastAPI backend
  const createPayPalOrder = async () => {
    setPayPalModal((prev) => ({ ...prev, status: 'initiating', error: null }));
    try {
      let response;
      if (payPalModal.paymentId) {
        response = await apiClient.request(
          API_ENDPOINTS.PAYMENTS.CREATE_ORDER_FOR_PAYMENT(payPalModal.paymentId),
          {
            method: 'POST',
            body: JSON.stringify({
              return_url: `${window.location.origin}/payment/success`,
              cancel_url: `${window.location.origin}/payment/cancel`,
            }),
          }
        );
      } else {
        response = await apiClient.request(API_ENDPOINTS.PAYMENTS.CREATE_ORDER, {
          method: 'POST',
          body: JSON.stringify({
            paymentId: payPalModal.paymentId,
            payerId: payPalModal.payerMemberId || payPalModal.payer?.id,
            expenseId: payPalModal.expenseId,
            receiverEmail: payPalModal.receiver?.paypalEmail,
            note: payPalModal.note,
          }),
        });
      }

      // Backend returns PaymentResponse with paypal_order_id
      const orderId = response.paypal_order_id || response.orderId || response.id;
      if (!orderId) {
        throw new Error('PayPal order created but no order ID returned from backend.');
      }

      setPayPalModal((prev) => ({
        ...prev,
        status: 'authorizing',
        orderId,
        paymentId: response.id || prev.paymentId,
      }));

      return orderId;
    } catch (err) {
      setPayPalModal((prev) => ({
        ...prev,
        status: 'error',
        error: err.detail || err.message || 'Failed to create PayPal order.',
      }));
      throw err;
    }
  };

  // Step 2: Capture PayPal Order via FastAPI backend upon genuine onApprove
  const capturePayPalOrder = async (orderId) => {
    setPayPalModal((prev) => ({ ...prev, status: 'capturing', error: null }));
    try {
      const activeOrderId = orderId || payPalModal.orderId;
      let response;

      if (payPalModal.paymentId) {
        response = await apiClient.request(
          API_ENDPOINTS.PAYMENTS.CAPTURE_FOR_PAYMENT(payPalModal.paymentId),
          {
            method: 'POST',
            body: JSON.stringify({ paypal_order_id: activeOrderId }),
          }
        );
      } else {
        response = await apiClient.request(API_ENDPOINTS.PAYMENTS.CAPTURE_ORDER, {
          method: 'POST',
          body: JSON.stringify({
            orderId: activeOrderId,
            paymentId: payPalModal.paymentId,
            payerId: payPalModal.payerMemberId || payPalModal.payer?.id,
          }),
        });
      }

      const captureStatus = (response.status || '').toLowerCase();
      if (captureStatus !== 'captured' && captureStatus !== 'completed') {
        throw new Error(`Unexpected capture status: ${response.status}. Please check payment history.`);
      }

      const captureId = response.paypal_capture_id || response.captureId || activeOrderId;

      // Mark matching debts as settled in expenses state
      setExpenses((prevExpenses) =>
        prevExpenses.map((exp) => {
          if (exp.paidBy === payPalModal.receiver?.id || exp.id === payPalModal.expenseId) {
            return {
              ...exp,
              splitDetails: (exp.splitDetails || []).map((detail) => {
                if (detail.userId === payPalModal.payer?.id) {
                  return { ...detail, isPaid: true };
                }
                return detail;
              }),
            };
          }
          return exp;
        })
      );

      // Refresh payment history from real backend
      await fetchPaymentHistory();

      setPayPalModal((prev) => ({
        ...prev,
        status: 'success',
        transactionId: captureId,
      }));

      // Fire celebratory confetti!
      confetti({
        particleCount: 120,
        spread: 80,
        origin: { y: 0.6 },
      });

      return { success: true, captureId, response };
    } catch (err) {
      setPayPalModal((prev) => ({
        ...prev,
        status: 'error',
        error: err.detail || err.message || 'Payment capture failed.',
      }));
      throw err;
    }
  };

  // Programmatic / fallback payment execution
  const executePayPalPayment = async () => {
    try {
      const orderId = await createPayPalOrder();
      return await capturePayPalOrder(orderId);
    } catch (err) {
      return { success: false, error: err.message };
    }
  };

  return (
    <ExpenseContext.Provider
      value={{
        groups,
        expenses,
        transactions,
        activeGroup,
        setActiveGroup,
        loading,
        error,
        summary,
        debtBreakdown,
        receiptScan,
        payPalModal,
        createGroup,
        addExpense,
        processReceiptFile,
        loadSampleReceipt,
        updateItemAssignment,
        updateReceiptMetadata,
        updateExtractedItem,
        resetReceiptScan,
        finalizeReceiptScan,
        openPayPalPayment,
        closePayPalModal,
        executePayPalPayment,
        createPayPalOrder,
        capturePayPalOrder,
        initializeExpensePayments,
        fetchPaymentHistory,
      }}
    >
      {children}
    </ExpenseContext.Provider>
  );
}

export const useExpenses = () => useContext(ExpenseContext);
