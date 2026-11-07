import React from 'react';
import {
  CheckCircle2,
  Trash2,
  Plus,
  Users
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
    activeGroup,
  } = useExpenses();
  const { allUsers } = useAuth();

  const data = receiptScan.extractedData;
  if (!data) return null;

  // Available group members for assignment
  const groupMembers = activeGroup?.members
    ? activeGroup.members.map((m) => allUsers.find((u) => u.id === m.userId)).filter(Boolean)
    : allUsers;

  const handleToggleMember = (itemId, userId, currentAssigned) => {
    let newAssigned;
    if (currentAssigned.includes(userId)) {
      newAssigned = currentAssigned.filter((id) => id !== userId);
      // ensure at least 1 person or allow empty
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
      price: 10.00,
      assignedTo: groupMembers.map((m) => m.id),
    };
    const updatedItems = [...data.items, newItem];
    const newSubtotal = updatedItems.reduce((sum, it) => sum + it.price, 0);
    const newTotal = newSubtotal + (data.tax || 0) + (data.tip || 0);

    updateReceiptMetadata('items', updatedItems);
    updateReceiptMetadata('subtotal', newSubtotal);
    updateReceiptMetadata('total', newTotal);
  };

  const handleDeleteItem = (itemId) => {
    const updatedItems = data.items.filter((it) => it.id !== itemId);
    const newSubtotal = updatedItems.reduce((sum, it) => sum + it.price, 0);
    const newTotal = newSubtotal + (data.tax || 0) + (data.tip || 0);

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
            <Badge variant="success" size="sm">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Verified by AI
            </Badge>
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

      {/* Editable Merchant Metadata Fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Merchant Name
          </label>
          <input
            type="text"
            value={data.merchant || ''}
            onChange={(e) => updateReceiptMetadata('merchant', e.target.value)}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Receipt Date
          </label>
          <input
            type="date"
            value={data.date || ''}
            onChange={(e) => updateReceiptMetadata('date', e.target.value)}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Sales Tax ($)
          </label>
          <input
            type="number"
            step="0.01"
            value={data.tax ?? ''}
            onChange={(e) => {
              const val = parseFloat(e.target.value) || 0;
              updateReceiptMetadata('tax', val);
              updateReceiptMetadata('total', (data.subtotal || 0) + val + (data.tip || 0));
            }}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            Tip / Gratuity ($)
          </label>
          <input
            type="number"
            step="0.01"
            value={data.tip ?? ''}
            onChange={(e) => {
              const val = parseFloat(e.target.value) || 0;
              updateReceiptMetadata('tip', val);
              updateReceiptMetadata('total', (data.subtotal || 0) + (data.tax || 0) + val);
            }}
            className="w-full px-3 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
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
                      min="1"
                      value={item.quantity}
                      onChange={(e) => {
                        const updated = data.items.map((it) =>
                          it.id === item.id ? { ...it, quantity: parseInt(e.target.value) || 1 } : it
                        );
                        updateReceiptMetadata('items', updated);
                      }}
                      className="w-12 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-center"
                    />
                  </div>

                  <div className="flex items-center gap-1 font-mono text-sm font-bold text-slate-900 dark:text-white">
                    <span>$</span>
                    <input
                      type="number"
                      step="0.01"
                      value={item.price}
                      onChange={(e) => {
                        const newPrice = parseFloat(e.target.value) || 0;
                        const updated = data.items.map((it) =>
                          it.id === item.id ? { ...it, price: newPrice } : it
                        );
                        const newSub = updated.reduce((s, it) => s + it.price, 0);
                        updateReceiptMetadata('items', updated);
                        updateReceiptMetadata('subtotal', newSub);
                        updateReceiptMetadata('total', newSub + (data.tax || 0) + (data.tip || 0));
                      }}
                      className="w-20 px-1.5 py-0.5 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-right"
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
