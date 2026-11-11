import React, { createContext, useContext, useState, useMemo, useEffect } from 'react';
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
  // Merge: keep both allUsers (HEAD) and isAuthenticated (origin/main)
  const { currentUser, isAuthenticated, allUsers } = useAuth();
  const [groups, setGroups] = useState(MOCK_GROUPS);
  const [expenses, setExpenses] = useState(MOCK_EXPENSES);
  const [transactions, setTransactions] = useState(MOCK_PAYPAL_TRANSACTIONS);
  const [activeGroup, setActiveGroup] = useState(MOCK_GROUPS[0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Active receipt scan session
  // Merge: HEAD has 'pending' status state; origin/main has extractionStatus, warnings, receiptId fields
  const [receiptScan, setReceiptScan] = useState({
    status: 'idle', // 'idle' | 'uploading' | 'processing' | 'pending' | 'review' | 'error'
    file: null,
    previewUrl: null,
    progress: 0,
    receiptId: null,
    extractionStatus: null, // 'pending' | 'processing' | 'completed' | 'review_required' | 'failed'
    extractedData: null,
    confidence: null,
    warnings: null,
    error: null,
    editedFields: {}, // HEAD: tracks edited fields
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
    paymentId: null,
    status: 'idle', // 'idle' | 'initiating' | 'authorizing' | 'capturing' | 'success' | 'error'
    transactionId: null,
    error: null,
  });

  // Merge: origin/main loads on isAuthenticated change; HEAD has initial data load with health check
  // Keep origin/main's approach (simpler, more reliable) while preserving fallback to mock
  useEffect(() => {
    if (isAuthenticated && currentUser) {
      loadGroupsAndExpenses();
    }
  }, [isAuthenticated, currentUser]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load groups and expenses from backend (origin/main)
  const loadGroupsAndExpenses = async () => {
    try {
      setLoading(true);

      // Load groups with members
      const groupsResponse = await apiClient.request(API_ENDPOINTS.GROUPS.LIST);

      // Load members for each group
      const groupsWithMembers = await Promise.all(
        groupsResponse.map(async (group) => {
          try {
            const members = await apiClient.request(API_ENDPOINTS.GROUPS.MEMBERS(group.id));
            return { ...group, members };
          } catch (err) {
            console.error(`[SplitMate] Failed to load members for group ${group.id}:`, err);
            return { ...group, members: [] };
          }
        })
      );

      setGroups(groupsWithMembers);
      if (groupsWithMembers.length > 0 && !activeGroup) {
        setActiveGroup(groupsWithMembers[0]);
      }

      // Load expenses
      const expensesResponse = await apiClient.request(API_ENDPOINTS.EXPENSES.LIST);
      setExpenses(expensesResponse);

    } catch (err) {
      console.error('[SplitMate] Failed to load groups and expenses:', err);
      // Fall back to mock data on error
      setGroups(MOCK_GROUPS);
      setExpenses(MOCK_EXPENSES);
    } finally {
      setLoading(false);
    }
  };

  // Load expenses for the active group from backend
  const loadGroupExpenses = async (groupId) => {
    if (!groupId) return;

    try {
      setLoading(true);
      const expensesResponse = await apiClient.request(API_ENDPOINTS.EXPENSES.LIST);
      // Filter by group on client side
      const groupExpenses = expensesResponse.filter(exp => exp.group_id === groupId);
      setExpenses(groupExpenses);
    } catch (err) {
      console.error('[SplitMate] Failed to load group expenses:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

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

        const debtor = split.userId;
        const creditor = payerId;
        const amount = split.share;
        const paymentId = split.paymentId || null;

        const key = `${debtor}->${creditor}`;
        const reverseKey = `${creditor}->${debtor}`;

        if (debtsMap.has(reverseKey)) {
          const existing = debtsMap.get(reverseKey);
          if (existing.amount >= amount) {
            debtsMap.set(reverseKey, { ...existing, amount: existing.amount - amount });
          } else {
            debtsMap.delete(reverseKey);
            debtsMap.set(key, { amount: amount - existing.amount, paymentId });
          }
        } else {
          const current = debtsMap.get(key) || { amount: 0, paymentId };
          debtsMap.set(key, { amount: current.amount + amount, paymentId: paymentId || current.paymentId });
        }
      });
    });

    const result = [];
    debtsMap.forEach((data, key) => {
      const amt = data.amount;
      if (amt <= 0.01) return;
      const [debtorId, creditorId] = key.split('->');
      const safeAllUsers = Array.isArray(allUsers) ? allUsers : [];
      const debtor = safeAllUsers.find((u) => u.id === debtorId) || MOCK_USERS.find((u) => u.id === debtorId) || { id: debtorId, name: 'User' };
      const creditor = safeAllUsers.find((u) => u.id === creditorId) || MOCK_USERS.find((u) => u.id === creditorId) || { id: creditorId, name: 'User' };

      result.push({
        id: key,
        debtor,
        creditor,
        amount: Number(amt.toFixed(2)),
        paymentId: data.paymentId,
        isCurrentUserDebtor: debtorId === currentUser.id,
        isCurrentUserCreditor: creditorId === currentUser.id,
      });
    });

    return result;
  }, [expenses, currentUser, allUsers]);

  // Create Group
  const createGroup = async (groupData) => {
    setLoading(true);
    try {
      // 1. Create group on FastAPI backend
      const response = await apiClient.request(API_ENDPOINTS.GROUPS.CREATE, {
        method: 'POST',
        body: JSON.stringify({ name: groupData.name }),
      });

      const newGroupId = response.id;

      // 2. Add members to group on backend
      const safeAllUsers = Array.isArray(allUsers) ? allUsers : [];
      const memberIds = groupData.memberIds || safeAllUsers.map((u) => u.id);
      const addedMembers = [];

      for (const uId of memberIds) {
        const userObj = safeAllUsers.find((u) => u.id === uId) || MOCK_USERS.find((u) => u.id === uId);
        if (userObj) {
          try {
            const added = await apiClient.request(API_ENDPOINTS.GROUPS.ADD_MEMBER(newGroupId), {
              method: 'POST',
              body: JSON.stringify({
                name: userObj.name,
                email: userObj.email || `${userObj.id}@splitmate.io`,
              }),
            });
            addedMembers.push({
              userId: added.id,
              name: added.name,
              email: added.email,
              role: 'Member',
            });
          } catch (e) {
            console.warn('Could not add member to backend group:', e);
          }
        }
      }

      const fullGroup = {
        ...response,
        description: groupData.description || 'SplitMate Squad',
        category: groupData.category || 'General',
        currency: groupData.currency || 'USD',
        members: addedMembers.length > 0 ? addedMembers : memberIds.map((id) => ({ userId: id, role: 'Member' })),
        totalExpenses: 0,
        userBalance: 0,
      };

      setGroups((prev) => [fullGroup, ...prev]);
      setActiveGroup(fullGroup);
      return { success: true, group: fullGroup };
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

  // Start Receipt Extraction using the real backend contract:
  //   Step 1: POST /api/receipts/upload  → returns {id, extraction_status: 'PENDING', ...}
  //   Step 2: Poll GET /api/receipts/{id} until extraction_status === 'COMPLETED'
  //            (Pawan's AI service calls POST /api/receipts/{id}/extraction when done)
  //   Step 3: Map completed ReceiptResponse into extractedData state
  const processReceiptFile = async (file) => {
    const previewUrl = URL.createObjectURL(file);
    setReceiptScan({
      status: 'uploading',
      file,
      previewUrl,
      progress: 15,
      receiptId: null,
      extractionStatus: 'pending',
      extractedData: null,
      confidence: null,
      warnings: null,
      error: null,
      editedFields: {},
    });

    try {
      // Step 1: Upload using multipart field name 'file' required by FastAPI
      const formData = new FormData();
      formData.append('file', file);

      // Call POST /api/receipts/extract which returns HTTP 202 with receipt_id & extraction_status
      const initResponse = await apiClient.request(API_ENDPOINTS.RECEIPTS.EXTRACT, {
        method: 'POST',
        body: formData,
        isFormData: true,
      });

      const receiptId = initResponse.receipt_id;
      const initialStatus = initResponse.extraction_status || 'pending';

      setReceiptScan((prev) => ({
        ...prev,
        status: 'processing',
        receiptId,
        extractionStatus: initialStatus,
        progress: 30,
      }));

      // Step 2: Poll GET /api/receipts/{receipt_id} until completed, review_required, or failed
      const MAX_POLL_ATTEMPTS = 35; // ~60 seconds max
      const POLL_INTERVAL_MS = 1800;
      let pollCount = 0;
      let finalResult = null;

      while (pollCount < MAX_POLL_ATTEMPTS) {
        pollCount++;
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));

        let res;
        try {
          res = await apiClient.request(API_ENDPOINTS.RECEIPTS.DETAILS(receiptId));
        } catch (pollErr) {
          console.warn(`[SplitMate] Receipt poll attempt ${pollCount} failed:`, pollErr);
          if (pollCount >= MAX_POLL_ATTEMPTS) {
            throw pollErr;
          }
          continue;
        }

        const currentStatus = res.extraction_status;

        // Keep updating progress while pending or processing
        setReceiptScan((prev) => ({
          ...prev,
          receiptId,
          extractionStatus: currentStatus,
          progress: Math.min(92, 30 + Math.floor((pollCount / MAX_POLL_ATTEMPTS) * 60)),
        }));

        if (currentStatus === 'completed' || currentStatus === 'review_required') {
          finalResult = res;
          break;
        } else if (currentStatus === 'failed') {
          throw new Error(res.error_message || res.error_code || 'Receipt extraction failed. Please try a clearer receipt image.');
        }
        // If pending or processing, continue polling without treating as error
      }

      if (!finalResult) {
        throw new Error('Receipt extraction timed out while waiting for AI analysis. Please try again.');
      }

      // Step 3: Map line items preserving null values (do not fabricate defaults)
      const defaultMembers = activeGroup?.members?.map((m) => m.userId) || [currentUser?.id].filter(Boolean);
      const itemsWithAssignments = (finalResult.items || []).map((item) => ({
        id: item.id,
        name: item.item_name || 'Item',
        quantity: item.quantity != null ? Number(item.quantity) : null,
        unit_price: item.unit_price != null ? Number(item.unit_price) : null,
        price: item.total_price != null ? Number(item.total_price) : null,
        assignedTo: [...defaultMembers],
      }));

      const extractedData = {
        receiptId: finalResult.receipt_id,
        merchant: finalResult.merchant_name != null ? finalResult.merchant_name : null,
        currency: finalResult.currency != null ? finalResult.currency : null,
        subtotal: finalResult.subtotal != null ? Number(finalResult.subtotal) : null,
        tax: finalResult.tax != null ? Number(finalResult.tax) : null,
        tip: null,
        total: finalResult.total != null ? Number(finalResult.total) : null,
        confidence: finalResult.confidence != null ? finalResult.confidence : null,
        warnings: finalResult.warnings || null,
        missingFields: finalResult.missing_fields || null,
        uncertainFields: finalResult.uncertain_fields || null,
        extractionStatus: finalResult.extraction_status,
        isUserReviewed: finalResult.is_user_reviewed || false,
        items: itemsWithAssignments,
      };

      setReceiptScan({
        status: 'review',
        file,
        previewUrl,
        progress: 100,
        receiptId: finalResult.receipt_id,
        extractionStatus: finalResult.extraction_status,
        extractedData,
        confidence: finalResult.confidence != null ? finalResult.confidence : null,
        warnings: finalResult.warnings || null,
        error: null,
        editedFields: {},
      });
    } catch (err) {
      console.error('[SplitMate] Receipt extraction failed:', err);
      setReceiptScan((prev) => ({
        ...prev,
        status: 'error',
        error: err.message || 'AI extraction failed. Please try a clearer receipt image.',
      }));
    }
  };

  // Submit human-reviewed corrections for a receipt in review_required status (origin/main)
  const submitReceiptReview = async (customData) => {
    if (!receiptScan.receiptId || !receiptScan.extractedData) return;
    const current = customData || receiptScan.extractedData;

    const currency = (current.currency || '').trim().toUpperCase();
    if (!currency || currency.length !== 3) {
      throw new Error("Valid 3-letter currency code (e.g. USD, EUR, INR) is required for review.");
    }
    if (current.total == null || isNaN(Number(current.total)) || Number(current.total) <= 0) {
      throw new Error("A positive total is required for review.");
    }
    if (!current.items || current.items.length === 0) {
      throw new Error("At least one line item is required for review.");
    }

    const payload = {
      merchant_name: current.merchant || null,
      currency,
      subtotal: current.subtotal != null ? Number(current.subtotal) : null,
      tax: current.tax != null ? Number(current.tax) : null,
      total: Number(current.total),
      items: current.items.map((it, idx) => {
        const qty = it.quantity != null && Number(it.quantity) > 0 ? Number(it.quantity) : 1;
        const tot = it.price != null && Number(it.price) >= 0 ? Number(it.price) : 0;
        let unit = it.unit_price != null && Number(it.unit_price) >= 0 ? Number(it.unit_price) : 0;
        if (Math.abs(qty * unit - tot) > 0.009) {
          unit = Number((tot / qty).toFixed(2));
        }
        return {
          item_name: it.name || `Item ${idx + 1}`,
          quantity: qty,
          unit_price: unit,
          total_price: Number((qty * unit).toFixed(2)),
        };
      }),
    };

    const res = await apiClient.request(API_ENDPOINTS.RECEIPTS.REVIEW(receiptScan.receiptId), {
      method: 'PUT',
      body: JSON.stringify(payload),
    });

    setReceiptScan((prev) => {
      if (!prev.extractedData) return prev;
      return {
        ...prev,
        extractionStatus: res.extraction_status,
        warnings: res.warnings || null,
        extractedData: {
          ...prev.extractedData,
          merchant: res.merchant_name,
          currency: res.currency,
          subtotal: res.subtotal != null ? Number(res.subtotal) : null,
          tax: res.tax != null ? Number(res.tax) : null,
          total: res.total != null ? Number(res.total) : null,
          extractionStatus: res.extraction_status,
          isUserReviewed: res.is_user_reviewed,
        },
      };
    });

    return res;
  };

  // Reset Receipt Scan State cleanly (HEAD version — revokes blob URL)
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
      receiptId: null,
      extractionStatus: null,
      extractedData: null,
      confidence: null,
      warnings: null,
      error: null,
      editedFields: {},
    });
  };

  // Load Sample Receipt for one-click demo (HEAD)
  const loadSampleReceipt = (sampleId) => {
    const sample = MOCK_SAMPLE_RECEIPTS.find((s) => s.id === sampleId) || MOCK_SAMPLE_RECEIPTS[0];
    setReceiptScan({
      status: 'review',
      file: null,
      previewUrl: sample.image,
      progress: 100,
      receiptId: null,
      extractionStatus: 'completed',
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
      warnings: null,
      error: null,
      editedFields: {},
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
        editedFields: { ...prev.editedFields, [field]: true },
        extractedData: {
          ...prev.extractedData,
          [field]: value,
        },
      };
    });
  };

  // Update a single extracted item field (HEAD: updateExtractedItem)
  const updateExtractedItem = (itemId, field, value) => {
    setReceiptScan((prev) => {
      if (!prev.extractedData) return prev;
      const updatedItems = prev.extractedData.items.map((item) => {
        if (item.id === itemId) {
          return { ...item, [field]: value };
        }
        return item;
      });
      return {
        ...prev,
        editedFields: { ...prev.editedFields, [`item_${itemId}_${field}`]: true },
        extractedData: {
          ...prev.extractedData,
          items: updatedItems,
        },
      };
    });
  };

  // Finalize receipt scan into an expense with real backend persistence (origin/main)
  const finalizeReceiptScan = async (targetGroupId, paidByUserId) => {
    if (!receiptScan.extractedData || !receiptScan.receiptId) {
      throw new Error('No receipt data available to finalize');
    }

    // Gate: Do not allow payment initialization until extraction is completed
    if (receiptScan.extractionStatus !== 'completed') {
      throw new Error(
        `Receipt extraction status is '${receiptScan.extractionStatus}'. Human review must be completed before splitting or initializing payments.`
      );
    }

    const data = receiptScan.extractedData;
    const targetGroup = groups.find((g) => g.id === targetGroupId) || activeGroup;

    if (!targetGroup || !targetGroup.members || targetGroup.members.length === 0) {
      throw new Error('Target group must have at least one member');
    }

    // Check if expense already exists for this receipt
    const existingExpense = expenses.find(exp => exp.receipt_id === receiptScan.receiptId || exp.receiptId === receiptScan.receiptId);
    if (existingExpense) {
      console.log('[SplitMate] Expense already exists for this receipt:', existingExpense.id);
      setReceiptScan({
        status: 'idle',
        file: null,
        previewUrl: null,
        progress: 0,
        receiptId: null,
        extractionStatus: null,
        extractedData: null,
        confidence: null,
        warnings: null,
        error: null,
        editedFields: {},
      });
      confetti({
        particleCount: 80,
        spread: 60,
        origin: { y: 0.6 },
      });
      return existingExpense;
    }

    setLoading(true);
    try {
      // Step 1: Create expense linked to receipt
      const expensePayload = {
        group_id: targetGroupId,
        receipt_id: receiptScan.receiptId,
        total_amount: Number(data.total),
        currency: data.currency || 'USD',
      };

      const expenseResponse = await apiClient.request(API_ENDPOINTS.EXPENSES.CREATE, {
        method: 'POST',
        body: JSON.stringify(expensePayload),
      });

      const expenseId = expenseResponse.id;

      // Step 2: Build assignment batch from item assignments
      // Map frontend user IDs to backend member IDs
      const userIdToMemberId = {};
      targetGroup.members.forEach((member) => {
        const uid = member.userId || member.user_id;
        if (uid) {
          userIdToMemberId[uid] = member.id;
        }
      });

      // For each receipt item, create assignments for each assigned user
      const assignments = [];
      data.items.forEach((item) => {
        const assignedUserIds = item.assignedTo || [];
        if (assignedUserIds.length === 0) {
          throw new Error(`Item "${item.name}" has no assignments`);
        }

        // Calculate share quantity per user (split equally among assigned users)
        const itemQuantity = item.quantity != null ? Number(item.quantity) : 1;
        const sharePerUser = itemQuantity / assignedUserIds.length;

        assignedUserIds.forEach((userId) => {
          const memberId = userIdToMemberId[userId];
          if (!memberId) {
            throw new Error(`User ${userId} is not a member of the target group`);
          }

          assignments.push({
            receipt_item_id: item.id,
            member_id: memberId,
            share_quantity: Number(sharePerUser.toFixed(4)),
          });
        });
      });

      // Step 3: Submit assignments to backend
      await apiClient.request(API_ENDPOINTS.EXPENSES.ASSIGN(expenseId), {
        method: 'POST',
        body: JSON.stringify({ assignments }),
      });

      // Step 4: Fetch calculated splits from backend
      const splitsResponse = await apiClient.request(API_ENDPOINTS.EXPENSES.SPLITS(expenseId));

      // Step 5: Initialize payments
      const paymentsResponse = await apiClient.request(
        API_ENDPOINTS.EXPENSES.INITIALIZE_PAYMENTS(expenseId),
        {
          method: 'POST',
        }
      );

      // Step 6: Update local state with backend response
      const newExpense = {
        id: expenseResponse.id,
        groupId: expenseResponse.group_id,
        receiptId: expenseResponse.receipt_id,
        receipt_id: expenseResponse.receipt_id,
        description: `${data.merchant || 'Receipt'} (AI Receipt Split)`,
        amount: expenseResponse.total_amount,
        currency: expenseResponse.currency,
        date: new Date(expenseResponse.created_at).toISOString().split('T')[0],
        paidBy: paidByUserId,
        splitType: 'ITEMIZED',
        splitDetails: splitsResponse.splits.map((split) => ({
          userId: split.member_id,
          userName: split.member_name,
          userEmail: split.member_email,
          share: Number(split.amount),
          isPaid: false,
        })),
        payments: paymentsResponse,
      };

      setExpenses((prev) => [newExpense, ...prev]);

      // Reset scan state cleanly
      resetReceiptScan();

      confetti({
        particleCount: 120,
        spread: 80,
        origin: { y: 0.6 },
      });

      return newExpense;
    } catch (err) {
      console.error('[SplitMate] Expense finalization failed:', err);
      setError(err.message || 'Failed to create expense');
      throw err;
    } finally {
      setLoading(false);
    }
  };

  // Open PayPal Payment Modal for a debt
  const openPayPalPayment = ({ creditor, debtor, amount, note, groupId, paymentId }) => {
    setPayPalModal({
      isOpen: true,
      payer: debtor || currentUser,
      receiver: creditor,
      amount,
      currency: 'USD',
      note: note || `Settle balance with ${creditor.name}`,
      groupId,
      paymentId: paymentId || null,
      status: 'idle',
      transactionId: null,
      error: null,
    });
  };

  const closePayPalModal = () => {
    setPayPalModal((prev) => ({ ...prev, isOpen: false, status: 'idle', error: null }));
  };

<<<<<<< HEAD
  // Execute PayPal Payment Flow
  // Merge: HEAD has resilient mock fallback; origin/main has approval_url support and real capture endpoint
  const executePayPalPayment = async (paymentId) => {
    const resolvedPaymentId = paymentId || payPalModal.paymentId;

    setPayPalModal((prev) => ({ ...prev, status: 'initiating', error: null }));

=======
  // Fetch real payment history from backend (Tanay's GET /api/payments/history)
  const fetchPaymentHistory = async () => {
>>>>>>> fbd9119 (Fix PayPal Sandbox integration and resolve merge conflicts)
    try {
      let captureId = null;
      let orderId = null;
      let captureResponse = null;

      const isRealUUID = (id) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);

      if (resolvedPaymentId && isRealUUID(resolvedPaymentId)) {
        // Step 1: Create PayPal Order
        const orderResponse = await apiClient.request(
          API_ENDPOINTS.PAYMENTS.CREATE_ORDER(resolvedPaymentId),
          {
            method: 'POST',
            body: JSON.stringify({
              return_url: window.location.href,
              cancel_url: window.location.href,
            }),
          }
        );

        orderId = orderResponse.paypal_order_id;

        // If we get an approval URL, open it in a new tab
        if (orderResponse.approval_url) {
          window.open(orderResponse.approval_url, '_blank');
        }

        setPayPalModal((prev) => ({ ...prev, status: 'authorizing' }));

        // Wait for user to complete PayPal checkout
        await new Promise((r) => setTimeout(r, 1000));

        // Step 2: Capture Order
        setPayPalModal((prev) => ({ ...prev, status: 'capturing' }));
        captureResponse = await apiClient.request(
          API_ENDPOINTS.PAYMENTS.CAPTURE(resolvedPaymentId),
          {
            method: 'POST',
            body: JSON.stringify({
              paypal_order_id: orderId,
            }),
          }
        );

        captureId = captureResponse.paypal_capture_id || orderId;
      } else {
        // Resilient sandbox flow for mock debts (HEAD fallback)
        setPayPalModal((prev) => ({ ...prev, status: 'authorizing' }));
        await new Promise((r) => setTimeout(r, 500));
        orderId = `MOCK-ORD-${Math.random().toString(36).substring(2, 10).toUpperCase()}`;

        setPayPalModal((prev) => ({ ...prev, status: 'capturing' }));
        await new Promise((r) => setTimeout(r, 600));
        captureId = `MOCK-CAP-${Math.random().toString(36).substring(2, 10).toUpperCase()}`;
        captureResponse = {
          paypal_capture_id: captureId,
          amount: payPalModal.amount,
          currency: payPalModal.currency,
          status: 'COMPLETED',
        };
      }

      // Step 3: Record transaction in state
      const newTxn = {
        id: `txn_pp_${Date.now()}`,
        orderId,
        captureId,
        payerId: payPalModal.payer?.id,
        payerName: payPalModal.payer?.name,
        receiverId: payPalModal.receiver?.id,
        receiverName: payPalModal.receiver?.name,
        receiverEmail: payPalModal.receiver?.paypalEmail || `${(payPalModal.receiver?.name || 'user').toLowerCase()}@sandbox.paypal.com`,
        amount: captureResponse.amount || payPalModal.amount,
        currency: captureResponse.currency || payPalModal.currency,
        date: new Date().toISOString(),
        status: captureResponse.status || 'COMPLETED',
        note: payPalModal.note,
        method: 'PayPal Sandbox Checkout',
      };

      setTransactions((prev) => [newTxn, ...prev]);

      // Mark split as paid
      setExpenses((prevExpenses) =>
        prevExpenses.map((exp) => {
          if (exp.paidBy === payPalModal.receiver?.id) {
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

      setPayPalModal((prev) => ({
        ...prev,
        status: 'success',
        transactionId: captureId,
      }));

      confetti({
        particleCount: 120,
        spread: 80,
        origin: { y: 0.6 },
      });

      return { success: true, captureId };
    } catch (err) {
      console.error('[SplitMate] PayPal payment failed:', err);
      setPayPalModal((prev) => ({
        ...prev,
        status: 'error',
        error: err.message || 'Payment processing failed. Please retry.',
      }));
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
        setReceiptScan,
        resetReceiptScan,
        payPalModal,
        createGroup,
        addExpense,
        loadGroupExpenses,
        loadGroupsAndExpenses,
        processReceiptFile,
        submitReceiptReview,
        loadSampleReceipt,
        updateItemAssignment,
        updateExtractedItem,
        updateReceiptMetadata,
        finalizeReceiptScan,
        openPayPalPayment,
        closePayPalModal,
        executePayPalPayment,
      }}
    >
      {children}
    </ExpenseContext.Provider>
  );
}

export const useExpenses = () => useContext(ExpenseContext);
