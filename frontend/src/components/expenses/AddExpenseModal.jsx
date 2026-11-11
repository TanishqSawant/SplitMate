import React, { useState } from 'react';
import { PlusCircle, DollarSign, Users, Calendar, Tag } from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { useAuth } from '../../context/AuthContext';
import Modal from '../common/Modal';
import Button from '../common/Button';

export default function AddExpenseModal({ isOpen, onClose }) {
  const { groups, activeGroup, addExpense } = useExpenses();
  const { allUsers, currentUser } = useAuth();

  const [description, setDescription] = useState('');
  const [amount, setAmount] = useState('');
  const [groupId, setGroupId] = useState(activeGroup?.id || groups[0]?.id);
  const [paidBy, setPaidBy] = useState(currentUser?.id);
  const [category, setCategory] = useState('Food & Dining');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [splitType, setSplitType] = useState('EQUAL'); // 'EQUAL'
  const [isSubmitting, setIsSubmitting] = useState(false);

  const selectedGroup = groups.find((g) => g.id === groupId) || groups[0];
  const groupMembers = (selectedGroup?.members || []).map((m) =>
    allUsers.find((u) => u.id === m.userId)
  ).filter(Boolean);

  const parsedAmount = parseFloat(amount) || 0;
  const equalShare = groupMembers.length > 0 ? parsedAmount / groupMembers.length : 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!description.trim() || parsedAmount <= 0) return;

    setIsSubmitting(true);
    try {
      const totalCents = Math.round(parsedAmount * 100);
      const memberCount = groupMembers.length;
      const baseShareCents = Math.floor(totalCents / memberCount);
      let remainderCents = totalCents % memberCount;

      const splitDetails = groupMembers.map((member) => {
        let memberCents = baseShareCents;
        if (remainderCents > 0) {
          memberCents += 1;
          remainderCents -= 1;
        }
        return {
          userId: member.id,
          share: Number((memberCents / 100).toFixed(2)),
          isPaid: member.id === paidBy,
        };
      });

      await addExpense({
        description,
        amount: parsedAmount,
        currency: selectedGroup?.currency || 'USD',
        category,
        groupId,
        paidBy,
        date,
        splitType,
        splitDetails,
      });

      setDescription('');
      setAmount('');
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Add Manual Expense"
      subtitle="Record an expense and split equally across squad members"
      maxWidth="max-w-lg"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
            Description *
          </label>
          <input
            type="text"
            required
            placeholder="e.g. AWS Cloud GPU Credits"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full px-3.5 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Amount ($) *
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2.5 text-sm font-bold text-slate-400">
                $
              </span>
              <input
                type="number"
                step="0.01"
                min="0.01"
                required
                placeholder="0.00"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-full pl-8 pr-3.5 py-2 text-sm font-mono font-bold rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            >
              <option value="Food & Dining">Food & Dining</option>
              <option value="Groceries">Groceries</option>
              <option value="Travel">Travel</option>
              <option value="Utilities">Utilities</option>
              <option value="Coffee & Snacks">Coffee & Snacks</option>
              <option value="Project">Project Supplies</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Target Squad
            </label>
            <select
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            >
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Paid By
            </label>
            <select
              value={paidBy}
              onChange={(e) => setPaidBy(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            >
              {groupMembers.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} {m.id === currentUser?.id ? '(You)' : ''}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Live Equal Split Preview */}
        {parsedAmount > 0 && (
          <div className="p-3 rounded-xl bg-blue-50/60 dark:bg-blue-950/40 border border-blue-100 dark:border-blue-900/60 text-xs text-blue-900 dark:text-blue-300 space-y-1.5">
            <div className="flex justify-between font-bold">
              <span>Equal Share ({groupMembers.length} members):</span>
              <span className="font-mono text-sm">${equalShare.toFixed(2)} / member</span>
            </div>
            <p className="text-[11px] text-blue-700 dark:text-blue-400">
              Each member will be debited ${equalShare.toFixed(2)}. The payer ({groupMembers.find((m) => m.id === paidBy)?.name?.split(' ')[0]}) is credited ${(parsedAmount - equalShare).toFixed(2)}.
            </p>
          </div>
        )}

        <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex justify-end gap-2.5">
          <Button variant="ghost" size="md" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button variant="primary" size="md" isLoading={isSubmitting} type="submit">
            Add & Split
          </Button>
        </div>
      </form>
    </Modal>
  );
}

