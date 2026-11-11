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
  const { currentUser, allUsers } = useAuth();
  const [groups, setGroups] = useState(MOCK_GROUPS);
  const [expenses, setExpenses] = useState(MOCK_EXPENSES);
  const [transactions, setTransactions] = useState(MOCK_PAYPAL_TRANSACTIONS);
  const [activeGroup, setActiveGroup] = useState(MOCK_GROUPS[0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Active receipt scan session
  const [receiptScan, setReceiptScan] = useState({
    status: 'idle', // 'idle' | 'uploading' | 'processing' | 'pending' | 'review' | 'error'
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

  // Load groups from backend on mount if available
  useEffect(() => {
    let isMounted = true;
    async function initData() {
      try {
        const health = await apiClient.checkHealth();
        if (health.online && isMounted) {
          const backendGroups = await apiClient.request(API_ENDPOINTS.GROUPS.LIST);
          if (Array.isArray(backendGroups) && backendGroups.length > 0) {
            // Enhance backend groups with members
            const enhanced = await Promise.all(
              backendGroups.map(async (g) => {
                try {
                  const members = await apiClient.request(API_ENDPOINTS.GROUPS.MEMBERS(g.id));
                  return {
                    ...g,
                    description: g.description || 'SplitMate Squad',
                    category: g.category || 'Dining & Trip',
                    currency: g.currency || 'USD',
                    members: members.map((m) => ({
                      userId: m.id,
                      name: m.name,
                      email: m.email,
                      role: 'Member',
                    })),
                  };
                } catch {
                  return g;
                }
              })
            );
            if (isMounted) {
              setGroups(enhanced);
              if (enhanced[0]) setActiveGroup(enhanced[0]);
            }
          }
        }
      } catch (err) {
        console.warn('Initial backend sync skipped; using local state.', err);
      }
    }
    initData();
    return () => {
      isMounted = false;
    };
  }, []);

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
      const debtor = allUsers.find((u) => u.id === debtorId) || MOCK_USERS.find((u) => u.id === debtorId) || { id: debtorId, name: 'User' };
      const creditor = allUsers.find((u) => u.id === creditorId) || MOCK_USERS.find((u) => u.id === creditorId) || { id: creditorId, name: 'User' };

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
      const memberIds = groupData.memberIds || allUsers.map((u) => u.id);
      const addedMembers = [];

      for (const uId of memberIds) {
        const userObj = allUsers.find((u) => u.id === uId) || MOCK_USERS.find((u) => u.id === uId);
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

  // Reset Receipt Scan State cleanly
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


  // Finalize receipt scan into an expense and initialize payments
  const finalizeReceiptScan = async (targetGroupId, paidByUserId) => {
    if (!receiptScan.extractedData) return;

    const data = receiptScan.extractedData;
    const targetGroup = groups.find((g) => g.id === targetGroupId) || activeGroup;
    const groupMemberIds = targetGroup?.members?.map((m) => m.userId || m.id) || [currentUser.id];

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

    let createdBackendExpense = null;
    let paymentRecords = [];

    // Attempt real backend integration: Expense -> Assign -> Splits -> Initialize Payments
    const isRealUUID = (id) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);

    if (targetGroupId && isRealUUID(targetGroupId)) {
      try {
        // Sync any edited or newly added items to backend receipt first
        if (isRealUUID(data.receiptId) && data.items && data.items.length > 0) {
          try {
            const updatedReceipt = await apiClient.request(
              API_ENDPOINTS.RECEIPTS.UPDATE_ITEMS(data.receiptId),
              {
                method: 'PUT',
                body: JSON.stringify({
                  merchant_name: data.merchant,
                  currency: data.currency || 'USD',
                  tax: Number(data.tax || 0),
                  items: data.items.map((it) => ({
                    item_name: it.name || it.item_name || 'Item',
                    quantity: it.quantity || 1,
                    unit_price: Number(it.price || it.unit_price || 0),
                    total_price: Number(((it.price || it.unit_price || 0) * (it.quantity || 1)).toFixed(2)),
                  })),
                }),
              }
            );
            if (updatedReceipt?.items && updatedReceipt.items.length === data.items.length) {
              data.items.forEach((item, idx) => {
                item.id = updatedReceipt.items[idx].id;
              });
            }
          } catch (syncErr) {
            console.warn('Could not sync edited items to backend receipt:', syncErr);
          }
        }

        const expensePayload = {
          group_id: targetGroupId,
          receipt_id: isRealUUID(data.receiptId) ? data.receiptId : null,
          total_amount: Number(data.total.toFixed(2)),
          currency: data.currency || 'USD',
        };

        createdBackendExpense = await apiClient.request(API_ENDPOINTS.EXPENSES.CREATE, {
          method: 'POST',
          body: JSON.stringify(expensePayload),
        });

        // Batch assign items on backend if receipt items are UUIDs
        if (createdBackendExpense && isRealUUID(data.receiptId)) {
          const assignments = [];
          data.items.forEach((item) => {
            if (isRealUUID(item.id)) {
              const assignedMembers = item.assignedTo || groupMemberIds;
              const share = 1 / Math.max(1, assignedMembers.length);
              assignedMembers.forEach((mId) => {
                if (isRealUUID(mId)) {
                  assignments.push({
                    receipt_item_id: item.id,
                    member_id: mId,
                    share_quantity: Number(share.toFixed(4)),
                  });
                }
              });
            }
          });

          if (assignments.length > 0) {
            await apiClient.request(API_ENDPOINTS.EXPENSES.ASSIGN(createdBackendExpense.id), {
              method: 'POST',
              body: JSON.stringify({ assignments }),
            });

            // Initialize pending PayPal payments on backend
            paymentRecords = await apiClient.request(
              API_ENDPOINTS.EXPENSES.INITIALIZE_PAYMENTS(createdBackendExpense.id),
              { method: 'POST' }
            );
          }
        }
      } catch (err) {
        console.warn('Backend expense pipeline completed with local fallback:', err);
      }
    }

    // Map payment records by member
    const paymentMapByMember = {};
    if (Array.isArray(paymentRecords)) {
      paymentRecords.forEach((p) => {
        paymentMapByMember[p.member_id] = p.id;
      });
    }

    const splitDetails = groupMemberIds.map((uId) => ({
      userId: uId,
      share: Number((userShares[uId] || 0).toFixed(2)),
      isPaid: uId === paidByUserId,
      paymentId: paymentMapByMember[uId] || `pay_${Date.now()}_${uId}`,
    }));

    const newExpense = {
      id: createdBackendExpense?.id || `exp_${Date.now()}`,
      groupId: targetGroupId,
      description: `${data.merchant} (AI Receipt Split)`,
      amount: data.total,
      currency: data.currency || 'USD',
      category: data.category || 'Food & Dining',
      paidBy: paidByUserId || currentUser.id,
      date: data.date || new Date().toISOString().split('T')[0],
      receiptId: data.receiptId || `rcpt_${Date.now()}`,
      splitType: 'ITEMIZED',
      splitDetails,
    };

    setExpenses((prev) => [newExpense, ...prev]);

    // Reset scan state cleanly
    resetReceiptScan();

    // Fire celebratory confetti
    confetti({
      particleCount: 100,
      spread: 70,
      origin: { y: 0.6 }
    });

    return newExpense;
  };

  // Open PayPal Payment Modal
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

  // Execute PayPal Payment Flow (Tanay's integration)
  const executePayPalPayment = async () => {
    setPayPalModal((prev) => ({ ...prev, status: 'initiating', error: null }));

    try {
      let captureId = null;
      let orderId = null;

      const isRealUUID = (id) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);

      // If we have a backend payment UUID, use the real backend PayPal endpoints
      if (payPalModal.paymentId && isRealUUID(payPalModal.paymentId)) {
        // Step 1: Create Order
        setPayPalModal((prev) => ({ ...prev, status: 'initiating' }));
        const orderResponse = await apiClient.request(
          API_ENDPOINTS.PAYMENTS.CREATE_ORDER(payPalModal.paymentId),
          {
            method: 'POST',
            body: JSON.stringify({}),
          }
        );

        orderId = orderResponse.paypal_order_id;
        setPayPalModal((prev) => ({ ...prev, status: 'authorizing' }));
        await new Promise((r) => setTimeout(r, 600));

        // Step 2: Capture Payment
        setPayPalModal((prev) => ({ ...prev, status: 'capturing' }));
        const captureResponse = await apiClient.request(
          API_ENDPOINTS.PAYMENTS.CAPTURE_ORDER(payPalModal.paymentId),
          {
            method: 'POST',
            body: JSON.stringify({ paypal_order_id: orderId }),
          }
        );

        captureId = captureResponse.paypal_capture_id || orderId;
      } else {
        // Resilient sandbox flow for mock debts
        setPayPalModal((prev) => ({ ...prev, status: 'authorizing' }));
        await new Promise((r) => setTimeout(r, 500));
        orderId = `MOCK-ORD-${Math.random().toString(36).substring(2, 10).toUpperCase()}`;

        setPayPalModal((prev) => ({ ...prev, status: 'capturing' }));
        await new Promise((r) => setTimeout(r, 600));
        captureId = `MOCK-CAP-${Math.random().toString(36).substring(2, 10).toUpperCase()}`;
      }

      // Step 3: Record transaction in state
      const newTxn = {
        id: `txn_pp_${Date.now()}`,
        orderId: orderId,
        captureId: captureId,
        payerId: payPalModal.payer.id,
        payerName: payPalModal.payer.name,
        receiverId: payPalModal.receiver.id,
        receiverName: payPalModal.receiver.name,
        receiverEmail: payPalModal.receiver.paypalEmail || `${payPalModal.receiver.name.toLowerCase()}@sandbox.paypal.com`,
        amount: payPalModal.amount,
        currency: payPalModal.currency,
        date: new Date().toISOString(),
        status: 'COMPLETED',
        note: payPalModal.note,
        method: 'PayPal Sandbox Checkout',
      };

      setTransactions((prev) => [newTxn, ...prev]);

      // Mark matching debts as settled in expenses
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
        processReceiptFile,
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
