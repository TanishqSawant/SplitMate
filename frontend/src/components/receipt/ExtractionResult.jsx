import React, { useState } from 'react';
import {
  CheckCircle2,
  Trash2,
  Plus,
  Users,
  AlertCircle,
  Sparkles,
  Save,
  HelpCircle
} from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { useAuth } from '../../context/AuthContext';
import Badge from '../common/Badge';
import Button from '../common/Button';

export default function ExtractionResult() {
  const {
    receiptScan,
    updateItemAssignment,
    updateReceiptMetadata,
    submitReceiptReview,
    activeGroup,
  } = useExpenses();
  const { allUsers } = useAuth();

  const [isSubmittingReview, setIsSubmittingReview] = useState(false);
  const [reviewError, setReviewError] = useState(null);
  const [reviewSuccess, setReviewSuccess] = useState(false);

  const data = receiptScan.extractedData;
  if (!data) return null;

  const isReviewRequired = receiptScan.extractionStatus === 'review_required' || data.extractionStatus === 'review_required';
  const isCompleted = receiptScan.extractionStatus === 'completed' || data.extractionStatus === 'completed';

  // Available group members for assignment
  const groupMembers = activeGroup?.members
    ? activeGroup.members.map((m) => {
        // Handle both mock structure (userId) and backend structure (user_id)
        const uid = m.userId || m.user_id;
        return allUsers.find((u) => u.id === uid);
      }).filter(Boolean)
    : allUsers;

  const handleToggleMember = (itemId, userId, currentAssigned) => {
    let newAssigned;
    if (currentAssigned.includes(userId)) {
      newAssigned = currentAssigned.filter((id) => id !== userId);
    } else {
      newAssigned = [...currentAssigned, userId];
    }
    updateItemAssignment(itemId, newAssigned);
  };

  const handleAssignAll = (itemId) => {
    const allIds = groupMembers.map((m) => m.id);
    updateItemAssignment(itemId, allIds);
  };

  const handleAddItem = () => {
    const newItem = {
      id: `item_${Date.now()}`,
      name: 'New Custom Item',
      quantity: 1,
      unit_price: 10.00,
      price: 10.00,
      assignedTo: groupMembers.map((m) => m.id),
    };
    const updatedItems = [...data.items, newItem];
    const newSubtotal = updatedItems.reduce((sum, it) => sum + (it.price != null ? it.price : 0), 0);
    const newTotal = newSubtotal + (data.tax || 0) + (data.tip || 0);

    updateReceiptMetadata('items', updatedItems);
    updateReceiptMetadata('subtotal', newSubtotal);
    updateReceiptMetadata('total', newTotal);
  };

  const handleDeleteItem = (itemId) => {
    const updatedItems = data.items.filter((it) => it.id !== itemId);
    const newSubtotal = updatedItems.reduce((sum, it) => sum + (it.price != null ? it.price : 0), 0);
    const newTotal = newSubtotal + (data.tax || 0) + (data.tip || 0);

    updateReceiptMetadata('items', updatedItems);
    updateReceiptMetadata('subtotal', newSubtotal);
    updateReceiptMetadata('total', newTotal);
  };

  const handleSubmitReview = async () => {
    setReviewError(null);
    setReviewSuccess(false);
    setIsSubmittingReview(true);
    try {
      await submitReceiptReview();
      setReviewSuccess(true);
    } catch (err) {
      setReviewError(err.message || 'Failed to submit review corrections.');
    } finally {
      setIsSubmittingReview(false);
    }
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-6">
      {/* Header & Verification Notice */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-100 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-slate-900 dark:text-white">
              AI Extracted Line Items
            </h3>
            {isCompleted && (
              <Badge variant="success" size="sm">
                <CheckCircle2 className="w-3.5 h-3.5" />
                {data.isUserReviewed ? 'Reviewed & Completed' : 'Verified by AI'}
              </Badge>
            )}
            {isReviewRequired && (
              <Badge variant="warning" size="sm">
                <AlertCircle className="w-3.5 h-3.5" />
                Review Required
              </Badge>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Tap member avatars to assign individual dishes and items. Tax and tip are pro-rated automatically.
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          icon={Plus}
          onClick={handleAddItem}
        >
          Add Item
        </Button>
      </div>

      {/* Review Required Alert Banner */}
      {isReviewRequired && (
        <div className="p-4 rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-950/30 text-amber-900 dark:text-amber-200 space-y-2">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
            <h4 className="text-xs font-bold uppercase tracking-wider">
              Human Review & Verification Required
            </h4>
          </div>
          <p className="text-xs text-slate-600 dark:text-slate-300">
            The AI model identified missing or uncertain values. Please review merchant details, currency (3-letter ISO), total, and line items, then submit your corrections to finalize extraction.
          </p>
          {receiptScan.warnings && receiptScan.warnings.length > 0 && (
            <div className="pt-1 border-t border-amber-200/60 dark:border-amber-900/40">
              <p className="text-[11px] font-semibold text-amber-800 dark:text-amber-300">Model Warnings:</p>
              <ul className="list-disc list-inside text-[11px] text-amber-700 dark:text-amber-400">
                {receiptScan.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          {data.uncertainFields && data.uncertainFields.length > 0 && (
            <p className="text-[11px] text-amber-700 dark:text-amber-400">
              Uncertain fields: {data.uncertainFields.join(', ')}
            </p>
          )}
          {data.missingFields && data.missingFields.length > 0 && (
            <p className="text-[11px] text-amber-700 dark:text-amber-400">
              Missing fields: {data.missingFields.join(', ')}
            </p>
          )}
        </div>
      )}

      {/* Review Feedback Alerts */}
      {reviewError && (
        <div className="p-3 rounded-xl border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/40 text-xs text-rose-700 dark:text-rose-300 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
          <span>{reviewError}</span>
        </div>
      )}
      {reviewSuccess && (
        <div className="p-3 rounded-xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/40 text-xs text-emerald-700 dark:text-emerald-300 flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
          <span>Review corrections submitted successfully! Receipt extraction is now complete.</span>
        </div>
      )}

      {/* Editable Receipt Metadata Fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Merchant Name
          </label>
          <input
            type="text"
            placeholder="Merchant not detected"
            value={data.merchant ?? ''}
            onChange={(e) => updateReceiptMetadata('merchant', e.target.value || null)}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Currency (3-Letter ISO)
          </label>
          <input
            type="text"
            maxLength={3}
            placeholder="e.g. USD, EUR"
            value={data.currency ?? ''}
            onChange={(e) => updateReceiptMetadata('currency', e.target.value ? e.target.value.toUpperCase() : null)}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white uppercase font-mono focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Receipt Date
          </label>
          <input
            type="date"
            value={data.date ?? ''}
            onChange={(e) => updateReceiptMetadata('date', e.target.value || null)}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Sales Tax
          </label>
          <input
            type="number"
            step="0.01"
            placeholder="—"
            value={data.tax ?? ''}
            onChange={(e) => {
              const val = e.target.value !== '' ? parseFloat(e.target.value) : null;
              updateReceiptMetadata('tax', val);
            }}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white font-mono focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Final Total
          </label>
          <input
            type="number"
            step="0.01"
            placeholder="—"
            value={data.total ?? ''}
            onChange={(e) => {
              const val = e.target.value !== '' ? parseFloat(e.target.value) : null;
              updateReceiptMetadata('total', val);
            }}
            className={`w-full px-3 py-2 text-xs font-bold rounded-xl border font-mono focus:ring-2 focus:ring-blue-500 ${
              data.total != null
                ? 'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white'
                : 'border-amber-300 dark:border-amber-700 bg-amber-50/50 dark:bg-amber-950/20 text-amber-600'
            }`}
          />
        </div>
      </div>

      {/* Interactive Line Items List */}
      <div className="space-y-3">
        {data.items.map((item, index) => {
          const assigned = item.assignedTo || [];
          const splitAmount = item.price != null && assigned.length > 0 ? item.price / assigned.length : item.price;

          return (
            <div
              key={item.id || index}
              className="p-4 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 hover:border-blue-300 dark:hover:border-blue-700 transition-all space-y-3"
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex-1 flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-400 w-5">
                    {index + 1}.
                  </span>
                  <input
                    type="text"
                    value={item.name}
                    placeholder="Item name"
                    onChange={(e) => {
                      const updated = data.items.map((it) =>
                        it.id === item.id ? { ...it, name: e.target.value } : it
                      );
                      updateReceiptMetadata('items', updated);
                    }}
                    className="flex-1 bg-transparent font-medium text-sm text-slate-900 dark:text-white border-b border-transparent hover:border-slate-300 dark:hover:border-slate-700 focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1 font-mono text-xs text-slate-500">
                    <span>Qty:</span>
                    <input
                      type="number"
                      step="any"
                      min="0.01"
                      placeholder="—"
                      value={item.quantity ?? ''}
                      onChange={(e) => {
                        const val = e.target.value !== '' ? parseFloat(e.target.value) : null;
                        const updated = data.items.map((it) =>
                          it.id === item.id ? { ...it, quantity: val } : it
                        );
                        updateReceiptMetadata('items', updated);
                      }}
                      className="w-14 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-center font-mono text-xs"
                    />
                  </div>

                  <div className="flex items-center gap-1 font-mono text-sm font-bold text-slate-900 dark:text-white">
                    <span className="text-xs text-slate-400">{data.currency || ''}</span>
                    <input
                      type="number"
                      step="0.01"
                      placeholder="—"
                      value={item.price ?? ''}
                      onChange={(e) => {
                        const val = e.target.value !== '' ? parseFloat(e.target.value) : null;
                        const updated = data.items.map((it) =>
                          it.id === item.id ? { ...it, price: val } : it
                        );
                        updateReceiptMetadata('items', updated);
                      }}
                      className="w-24 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-right font-mono"
                    />
                  </div>

                  <button
                    onClick={() => handleDeleteItem(item.id)}
                    className="p-1.5 text-slate-400 hover:text-rose-500 rounded-lg hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors"
                    title="Remove item"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Member Assignment Selector */}
              <div className="pt-2 border-t border-slate-200/60 dark:border-slate-800/60 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[11px] font-semibold text-slate-400 mr-1 flex items-center gap-1">
                    <Users className="w-3 h-3" />
                    Split with:
                  </span>
                  <button
                    type="button"
                    onClick={() => handleAssignAll(item.id)}
                    className="text-[10px] font-bold text-blue-600 dark:text-blue-400 hover:underline px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/60"
                  >
                    Everyone
                  </button>

                  {groupMembers.map((member) => {
                    const isAssigned = assigned.includes(member.id);
                    return (
                      <button
                        key={member.id}
                        type="button"
                        onClick={() => handleToggleMember(item.id, member.id, assigned)}
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-all ${
                          isAssigned
                            ? 'bg-blue-600 text-white font-medium shadow-xs scale-102'
                            : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 hover:border-blue-400'
                        }`}
                      >
                        <img
                          src={member.avatar}
                          alt={member.name}
                          className="w-3.5 h-3.5 rounded-full object-cover"
                        />
                        <span>{member.name.split(' ')[0]}</span>
                      </button>
                    );
                  })}
                </div>

                <div className="text-[11px] font-mono text-slate-500 dark:text-slate-400">
                  {assigned.length > 0 ? (
                    splitAmount != null ? (
                      <span>
                        {data.currency ? `${data.currency} ` : '$'}{splitAmount.toFixed(2)} / person ({assigned.length})
                      </span>
                    ) : (
                      <span className="text-amber-500 italic">Unpriced item</span>
                    )
                  ) : (
                    <span className="text-amber-500 font-medium">Unassigned</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Review Submission Action Bar (only when review is required) */}
      {isReviewRequired && (
        <div className="p-4 rounded-xl border border-amber-300 dark:border-amber-800/80 bg-gradient-to-r from-amber-50/90 to-orange-50/90 dark:from-amber-950/40 dark:to-orange-950/40 flex flex-col sm:flex-row items-center justify-between gap-3 shadow-xs">
          <div>
            <p className="text-xs font-bold text-amber-900 dark:text-amber-200 flex items-center gap-1.5">
              <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
              Human Review Corrections Ready
            </p>
            <p className="text-[11px] text-slate-600 dark:text-slate-400 mt-0.5">
              Submit confirmed merchant, currency, and line items to the backend review gate to complete extraction.
            </p>
          </div>
          <Button
            variant="primary"
            size="md"
            icon={CheckCircle2}
            isLoading={isSubmittingReview}
            onClick={handleSubmitReview}
            className="shrink-0 bg-amber-600 hover:bg-amber-700 text-white font-semibold"
          >
            Submit Review Corrections
          </Button>
        </div>
      )}
    </div>
  );
}
