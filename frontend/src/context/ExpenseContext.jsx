import React, { createContext, useContext, useState, useEffect, useMemo } from 'react';
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
    status: 'idle', // 'idle' | 'uploading' | 'processing' | 'review' | 'error'
    file: null,
    previewUrl: null,
    progress: 0,
    extractedData: null,
    confidence: null,
    error: null,
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

  // Start Receipt Extraction (Pawan's AI OCR)
  const processReceiptFile = async (file) => {
    const previewUrl = URL.createObjectURL(file);
    setReceiptScan({
      status: 'uploading',
      file,
      previewUrl,
      progress: 25,
      extractedData: null,
      confidence: null,
      error: null,
    });

    try {
      // Step 1: Uploading
      await new Promise((r) => setTimeout(r, 600));
      setReceiptScan((prev) => ({ ...prev, status: 'processing', progress: 65 }));

      // Step 2: Request extraction from Pawan's endpoint
      const formData = new FormData();
      // FastAPI's upload_receipt endpoint expects the multipart field name 'file'.
      formData.append('file', file);

      const uploadedReceipt = await apiClient.request(API_ENDPOINTS.RECEIPTS.UPLOAD, {
        method: 'POST',
        body: formData,
        isFormData: true,
      });

      setReceiptScan((prev) => ({ ...prev, progress: 100 }));
      await new Promise((r) => setTimeout(r, 400));

      // The current backend upload endpoint stores the receipt but does not run OCR.
      // It returns extraction_status='pending' until the AI service submits results.
      if (!uploadedReceipt.items || uploadedReceipt.items.length === 0) {
        setReceiptScan((prev) => ({
          ...prev,
          status: 'error',
          receiptId: uploadedReceipt.id,
          error: 'Receipt uploaded successfully, but AI extraction is not connected to the backend yet.',
        }));
        return;
      }

      const extraction = {
        merchant: uploadedReceipt.merchant_name,
        currency: uploadedReceipt.currency,
        subtotal: uploadedReceipt.subtotal,
        tax: uploadedReceipt.tax,
        total: uploadedReceipt.total,
        items: uploadedReceipt.items.map((item) => ({
          id: item.id,
          name: item.item_name,
          quantity: item.quantity,
          price: item.total_price,
        })),
      };

      // Items default assignment: assign each to all members of activeGroup or currentUser
      const defaultMembers = activeGroup?.members?.map((m) => m.userId) || [currentUser.id];
      const itemsWithAssignments = (extraction.items || []).map((item) => ({
        ...item,
        assignedTo: item.assignedTo || [...defaultMembers],
      }));

      setReceiptScan({
        status: 'review',
        file,
        previewUrl,
        progress: 100,
        extractedData: {
          ...extraction,
          items: itemsWithAssignments,
        },
        confidence: extraction.confidence || 0.95,
        error: null,
      });
    } catch (err) {
      setReceiptScan((prev) => ({
        ...prev,
        status: 'error',
        error: err.message || 'AI extraction failed. Please try a clearer receipt image.',
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

  // Fetch real payment history from backend (Tanay's GET /api/payments/history)
  const fetchPaymentHistory = async () => {
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
          API_ENDPOINTS.PAYMENTS.CREATE_ORDER(payPalModal.paymentId),
          {
            method: 'POST',
            body: JSON.stringify({
              return_url: `${window.location.origin}/payment/success`,
              cancel_url: `${window.location.origin}/payment/cancel`,
            }),
          }
        );
      } else {
        response = await apiClient.request(API_ENDPOINTS.PAYMENTS.PAYPAL_CREATE_DIRECT, {
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
          API_ENDPOINTS.PAYMENTS.CAPTURE(payPalModal.paymentId),
          {
            method: 'POST',
            body: JSON.stringify({ paypal_order_id: activeOrderId }),
          }
        );
      } else {
        response = await apiClient.request(API_ENDPOINTS.PAYMENTS.PAYPAL_CAPTURE_DIRECT, {
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
