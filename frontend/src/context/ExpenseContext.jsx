/* oxlint-disable react/only-export-components */
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
    paymentId: null,
    expenseId: null,
    payer: null,
    receiver: null,
    amount: 0,
    currency: 'USD',
    note: '',
    groupId: null,
    status: 'idle', // 'idle' | 'initiating' | 'authorizing' | 'capturing' | 'success' | 'cancelled' | 'error'
    orderId: null,
    transactionId: null,
    error: null,
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

  // Phase 4: Initialize payments on backend for an expense
  const initializeExpensePayments = async (expenseId) => {
    if (!expenseId) return { success: false, error: 'Expense ID required' };
    try {
      const initialized = await apiClient.request(API_ENDPOINTS.EXPENSES.INITIALIZE_PAYMENTS(expenseId), {
        method: 'POST',
      });
      return { success: true, payments: initialized };
    } catch (err) {
      return { success: false, error: err.message || 'Failed to initialize payments for expense.' };
    }
  };

  // Phase 8: Verify payment status from backend without blindly retrying capture
  const verifyPaymentStatus = async (paymentId) => {
    if (!paymentId) return null;
    try {
      const statusRes = await apiClient.request(API_ENDPOINTS.PAYMENTS.GET(paymentId), {
        method: 'GET',
      });
      return statusRes;
    } catch {
      return null;
    }
  };

  // Open PayPal Payment Modal for a debt or initialized payment
  const openPayPalPayment = ({ paymentId, expenseId, creditor, debtor, amount, note, groupId }) => {
    setPayPalModal({
      isOpen: true,
      paymentId: paymentId || null,
      expenseId: expenseId || null,
      payer: debtor || currentUser,
      receiver: creditor,
      amount: typeof amount === 'number' ? amount : parseFloat(amount || 0),
      currency: 'USD',
      note: note || `Settle balance with ${creditor?.name || 'teammate'}`,
      groupId,
      status: 'idle',
      orderId: null,
      transactionId: null,
      error: null,
    });
  };

  const closePayPalModal = () => {
    setPayPalModal((prev) => ({ ...prev, isOpen: false, status: 'idle', error: null }));
  };

  // Phase 6A: Real PayPal createOrder callback
  const createPayPalOrder = async () => {
    let paymentId = payPalModal.paymentId;

    // Auto-initialize payments if only expenseId is known
    if (!paymentId && payPalModal.expenseId) {
      try {
        const initRes = await initializeExpensePayments(payPalModal.expenseId);
        if (initRes.success && Array.isArray(initRes.payments)) {
          const myPayment = initRes.payments.find(
            (p) => p.member_id === payPalModal.payer?.id || p.member_id === currentUser?.id
          ) || initRes.payments[0];
          if (myPayment?.id) {
            paymentId = myPayment.id;
            setPayPalModal((prev) => ({ ...prev, paymentId: myPayment.id }));
          }
        }
      } catch (e) {
        console.warn('Auto-initialization of payments failed:', e);
      }
    }

    if (!paymentId) {
      const missingErr = 'Payment record ID is missing. The split payments must be initialized first on the backend.';
      setPayPalModal((prev) => ({ ...prev, status: 'error', error: missingErr }));
      throw new Error(missingErr);
    }

    // Duplicate create-order guard
    if (payPalModal.status === 'initiating' || payPalModal.status === 'authorizing') {
      if (payPalModal.orderId) return payPalModal.orderId;
    }

    setPayPalModal((prev) => ({ ...prev, status: 'initiating', error: null }));

    try {
      const response = await apiClient.request(API_ENDPOINTS.PAYMENTS.CREATE_ORDER(paymentId), {
        method: 'POST',
        body: JSON.stringify({}),
      });

      if (!response || !response.paypal_order_id) {
        throw new Error(
          response?.detail ||
          'Backend did not return a valid PayPal order ID. Ensure Tanay has connected the PayPal Sandbox Orders API.'
        );
      }

      setPayPalModal((prev) => ({
        ...prev,
        status: 'authorizing',
        orderId: response.paypal_order_id,
        amount: response.amount ? Number(response.amount) : prev.amount,
        currency: response.currency || prev.currency,
      }));

      return response.paypal_order_id;
    } catch (err) {
      const errMsg = err.status === 501
        ? "PayPal Sandbox backend integration is currently pending on the server (Tanay's module)."
        : (err.message || 'Failed to create PayPal Sandbox order.');
      setPayPalModal((prev) => ({
        ...prev,
        status: 'error',
        error: errMsg,
      }));
      throw new Error(errMsg);
    }
  };

  // Phase 6C & Phase 8: Real PayPal onApprove capture callback with backend verification
  const onApprovePayPalPayment = async (orderId) => {
    const paymentId = payPalModal.paymentId;
    if (!paymentId) {
      throw new Error('Payment record ID missing during capture.');
    }

    // Duplicate capture guard
    if (payPalModal.status === 'capturing' || payPalModal.status === 'success') {
      return;
    }

    setPayPalModal((prev) => ({ ...prev, status: 'capturing', error: null }));

    try {
      const response = await apiClient.request(API_ENDPOINTS.PAYMENTS.CAPTURE(paymentId), {
        method: 'POST',
        body: JSON.stringify({ paypal_order_id: orderId }),
      });

      // Strict validation: Only display success if backend confirms status === 'captured'
      if (response.status !== 'captured' && response.status !== 'COMPLETED') {
        throw new Error(`Payment status is '${response.status}'. Funds have not been captured.`);
      }

      const captureId = response.paypal_capture_id || response.id;

      // Phase 9: Update authoritative transaction history with backend record
      const newTxn = {
        id: response.id,
        orderId: response.paypal_order_id || orderId,
        captureId,
        payerId: payPalModal.payer.id,
        payerName: payPalModal.payer.name,
        receiverId: payPalModal.receiver.id,
        receiverName: payPalModal.receiver.name,
        receiverEmail: payPalModal.receiver.paypalEmail,
        amount: response.amount ? Number(response.amount) : payPalModal.amount,
        currency: response.currency || payPalModal.currency,
        date: response.updated_at || response.created_at || new Date().toISOString(),
        status: 'CAPTURED',
        note: payPalModal.note,
        method: 'PayPal Sandbox Checkout',
      };

      setTransactions((prev) => [newTxn, ...prev]);

      // Mark matching debts as settled in local expenses state
      setExpenses((prevExpenses) =>
        prevExpenses.map((exp) => {
          if (exp.paidBy === payPalModal.receiver.id) {
            return {
              ...exp,
              splitDetails: (exp.splitDetails || []).map((detail) => {
                if (detail.userId === payPalModal.payer.id) {
                  return { ...detail, isPaid: true };
                }
                return detail;
              }),
            };
          }
          return exp;
        })
      );

      setPayPalModal((prev) => ({
        ...prev,
        status: 'success',
        transactionId: captureId,
      }));

      // Fire celebratory confetti for the fintech win!
      confetti({
        particleCount: 120,
        spread: 80,
        origin: { y: 0.6 }
      });

      return { success: true, captureId };
    } catch (err) {
      // In case of timeout or network error during capture: check backend status first (Phase 8)
      const isNetworkErr = err.message?.toLowerCase().includes('network') || err.message?.toLowerCase().includes('connect');
      if (isNetworkErr) {
        const verified = await verifyPaymentStatus(paymentId);
        if (verified && verified.status === 'captured') {
          setPayPalModal((prev) => ({
            ...prev,
            status: 'success',
            transactionId: verified.paypal_capture_id || verified.id,
          }));
          return { success: true, captureId: verified.paypal_capture_id };
        }
      }

      setPayPalModal((prev) => ({
        ...prev,
        status: 'error',
        error: err.message || 'PayPal capture failed on the server. Please verify transaction.',
      }));
      throw err;
    }
  };

  const onCancelPayPalPayment = () => {
    setPayPalModal((prev) => ({
      ...prev,
      status: 'cancelled',
      error: 'PayPal checkout was cancelled. No charges were made.',
    }));
  };

  const resetPayPalPayment = () => {
    setPayPalModal((prev) => ({
      ...prev,
      status: 'idle',
      error: null,
    }));
  };

  const handlePayPalError = (err) => {
    setPayPalModal((prev) => ({
      ...prev,
      status: 'error',
      error: err?.message || 'PayPal Sandbox encountered an issue during checkout.',
    }));
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
        initializeExpensePayments,
        verifyPaymentStatus,
        createPayPalOrder,
        onApprovePayPalPayment,
        onCancelPayPalPayment,
        handlePayPalError,
        resetPayPalPayment,
      }}
    >
      {children}
    </ExpenseContext.Provider>
  );
}

export const useExpenses = () => useContext(ExpenseContext);
