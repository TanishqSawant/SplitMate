import React from 'react';
import {
  CheckCircle2,
  Trash2,
  Plus,
  Users,
  AlertTriangle,
  Edit3
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
    updateExtractedItem,
    activeGroup,
  } = useExpenses();
  const { allUsers } = useAuth();

  const data = receiptScan.extractedData;
  if (!data) return null;

  const edited = receiptScan.editedFields || {};
  const hasIncompleteFields = !data.merchant || !data.total || data.items.length === 0;

  // Available group members for assignment
  const groupMembers = activeGroup?.members
    ? activeGroup.members.map((m) => allUsers.find((u) => u.id === m.userId)).filter(Boolean)
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
      name: 'Custom Line Item',
      quantity: 1,
      price: 0.00,
      assignedTo: groupMembers.map((m) => m.id),
      isEdited: true,
    };
    const updatedItems = [...data.items, newItem];
    const newSubtotal = Number(updatedItems.reduce((sum, it) => sum + (it.price || 0), 0).toFixed(2));
    const newTotal = Number((newSubtotal + (data.tax || 0) + (data.tip || 0)).toFixed(2));

    updateReceiptMetadata('items', updatedItems);
    updateReceiptMetadata('subtotal', newSubtotal);
    updateReceiptMetadata('total', newTotal);
  };

  const handleDeleteItem = (itemId) => {
    const updatedItems = data.items.filter((it) => it.id !== itemId);
    const newSubtotal = Number(updatedItems.reduce((sum, it) => sum + (it.price || 0), 0).toFixed(2));
    const newTotal = Number((newSubtotal + (data.tax || 0) + (data.tip || 0)).toFixed(2));

    updateReceiptMetadata('items', updatedItems);
    updateReceiptMetadata('subtotal', newSubtotal);
    updateReceiptMetadata('total', newTotal);
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
            {receiptScan.confidence != null ? (
              <Badge variant="success" size="sm">
                <CheckCircle2 className="w-3.5 h-3.5" />
                Verified AI ({Math.round(receiptScan.confidence * 100)}%)
              </Badge>
            ) : (
              <Badge variant="default" size="sm">
                Unverified Review
              </Badge>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Review parsed items or edit quantities and amounts. Assign each dish to group members to split itemized shares.
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

      {/* Warnings & Diagnostics Banner */}
      {receiptScan.warnings && receiptScan.warnings.length > 0 && (
        <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/80 text-xs text-amber-800 dark:text-amber-200 space-y-1">
          <div className="flex items-center gap-1.5 font-bold">
            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
            <span>Extraction Verification Notes:</span>
          </div>
          <ul className="list-disc pl-5 space-y-0.5 text-[11px] text-amber-700 dark:text-amber-300">
            {receiptScan.warnings.map((w, idx) => (
              <li key={idx}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Incomplete Extraction Flag */}
      {hasIncompleteFields && (
        <div className="p-3.5 rounded-xl bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 text-xs text-blue-800 dark:text-blue-200 flex items-start gap-2">
          <Edit3 className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-bold">Manual Review Required</p>
            <p className="text-[11px] text-blue-700 dark:text-blue-300 mt-0.5">
              Some fields were not detected with 100% confidence. Please complete or adjust the merchant and total amounts below.
            </p>
          </div>
        </div>
      )}

      {/* Editable Merchant Metadata Fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Merchant Name
            </label>
            {edited.merchant && (
              <span className="text-[9px] text-blue-600 dark:text-blue-400 font-bold uppercase">(Edited)</span>
            )}
          </div>
          <input
            type="text"
            placeholder="e.g. Mario's Pizzeria"
            value={data.merchant || ''}
            onChange={(e) => updateReceiptMetadata('merchant', e.target.value)}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Receipt Date
            </label>
            {edited.date && (
              <span className="text-[9px] text-blue-600 dark:text-blue-400 font-bold uppercase">(Edited)</span>
            )}
          </div>
          <input
            type="date"
            value={data.date || ''}
            onChange={(e) => updateReceiptMetadata('date', e.target.value)}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Sales Tax ($)
            </label>
            {edited.tax && (
              <span className="text-[9px] text-blue-600 dark:text-blue-400 font-bold uppercase">(Edited)</span>
            )}
          </div>
          <input
            type="number"
            step="0.01"
            placeholder="0.00"
            value={data.tax ?? ''}
            onChange={(e) => {
              const val = e.target.value === '' ? null : (parseFloat(e.target.value) || 0);
              updateReceiptMetadata('tax', val);
              const sub = data.subtotal || 0;
              const tipVal = data.tip || 0;
              updateReceiptMetadata('total', Number((sub + (val || 0) + tipVal).toFixed(2)));
            }}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500 font-mono"
          />
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Tip / Gratuity ($)
            </label>
            {edited.tip && (
              <span className="text-[9px] text-blue-600 dark:text-blue-400 font-bold uppercase">(Edited)</span>
            )}
          </div>
          <input
            type="number"
            step="0.01"
            placeholder="0.00"
            value={data.tip ?? ''}
            onChange={(e) => {
              const val = e.target.value === '' ? null : (parseFloat(e.target.value) || 0);
              updateReceiptMetadata('tip', val);
              const sub = data.subtotal || 0;
              const taxVal = data.tax || 0;
              updateReceiptMetadata('total', Number((sub + taxVal + (val || 0)).toFixed(2)));
            }}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500 font-mono"
          />
        </div>
      </div>

      {/* Interactive Line Items List */}
      <div className="space-y-3">
        {data.items.map((item, index) => {
          const assigned = item.assignedTo || [];
          const splitAmount = assigned.length > 0 ? item.price / assigned.length : item.price;

          return (
            <div
              key={item.id || index}
              className={`p-4 rounded-xl border transition-all space-y-3 ${
                item.isEdited
                  ? 'border-blue-300 dark:border-blue-800 bg-blue-50/20 dark:bg-blue-950/20'
                  : 'border-slate-200/90 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 hover:border-slate-300 dark:hover:border-slate-700'
              }`}
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex-1 flex items-center gap-2">
                  <span className="font-mono text-xs text-slate-400 w-5">
                    {index + 1}.
                  </span>
                  <input
                    type="text"
                    value={item.name}
                    onChange={(e) => {
                      if (updateExtractedItem) {
                        updateExtractedItem(item.id, { name: e.target.value });
                      } else {
                        const updated = data.items.map((it) =>
                          it.id === item.id ? { ...it, name: e.target.value, isEdited: true } : it
                        );
                        updateReceiptMetadata('items', updated);
                      }
                    }}
                    className="flex-1 bg-transparent font-medium text-sm text-slate-900 dark:text-white border-b border-transparent hover:border-slate-300 dark:hover:border-slate-700 focus:border-blue-500 focus:outline-hidden"
                  />
                  {item.isEdited && (
                    <span className="text-[9px] text-blue-600 dark:text-blue-400 font-bold uppercase tracking-wider shrink-0">
                      Edited
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1 font-mono text-xs text-slate-500">
                    <span>Qty:</span>
                    <input
                      type="number"
                      min="1"
                      value={item.quantity}
                      onChange={(e) => {
                        const q = parseInt(e.target.value, 10) || 1;
                        if (updateExtractedItem) {
                          updateExtractedItem(item.id, { quantity: q });
                        } else {
                          const updated = data.items.map((it) =>
                            it.id === item.id ? { ...it, quantity: q, isEdited: true } : it
                          );
                          updateReceiptMetadata('items', updated);
                        }
                      }}
                      className="w-12 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white text-center font-bold"
                    />
                  </div>

                  <div className="flex items-center gap-1 font-mono text-sm font-bold text-slate-900 dark:text-white">
                    <span>$</span>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={item.price}
                      onChange={(e) => {
                        const p = parseFloat(e.target.value) || 0;
                        if (updateExtractedItem) {
                          updateExtractedItem(item.id, { price: p });
                        } else {
                          const updated = data.items.map((it) =>
                            it.id === item.id ? { ...it, price: p, isEdited: true } : it
                          );
                          const newSub = Number(updated.reduce((s, it) => s + (it.price || 0), 0).toFixed(2));
                          updateReceiptMetadata('items', updated);
                          updateReceiptMetadata('subtotal', newSub);
                          updateReceiptMetadata('total', Number((newSub + (data.tax || 0) + (data.tip || 0)).toFixed(2)));
                        }
                      }}
                      className="w-20 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white text-right"
                    />
                  </div>

                  <button
                    onClick={() => handleDeleteItem(item.id)}
                    className="p-1.5 text-slate-400 hover:text-rose-500 rounded-lg hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors cursor-pointer"
                    title="Remove item"
                    aria-label="Remove item"
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
                    className="text-[10px] font-bold text-blue-600 dark:text-blue-400 hover:underline px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/60 cursor-pointer"
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
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-all cursor-pointer ${
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
                    <span>
                      ${splitAmount.toFixed(2)} / person ({assigned.length})
                    </span>
                  ) : (
                    <span className="text-amber-500 font-medium">Unassigned</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
