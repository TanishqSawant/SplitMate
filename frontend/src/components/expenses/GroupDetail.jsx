import React, { useState } from 'react';
import {
  Users,
  Plus,
  ScanLine,
  Receipt,
  ArrowRight,
  ShieldCheck
} from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { useAuth } from '../../context/AuthContext';
import Button from '../common/Button';
import Badge from '../common/Badge';

export default function GroupDetail({
  onAddExpense,
  onScanReceipt,
  onSelectExpense,
}) {
  const { activeGroup, expenses } = useExpenses();
  const { currentUser, allUsers } = useAuth();
  const [filter, setFilter] = useState('ALL'); // 'ALL' | 'MINE'

  if (!activeGroup) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-12 text-center border border-slate-200 dark:border-slate-800">
        <Users className="w-12 h-12 text-slate-400 mx-auto mb-3" />
        <h3 className="text-base font-bold text-slate-800 dark:text-slate-200">
          No Group Selected
        </h3>
        <p className="text-xs text-slate-500 mt-1">
          Select a group from the list above or create a new one.
        </p>
      </div>
    );
  }

  // Expenses for this group
  const groupExpenses = expenses.filter((e) => e.groupId === activeGroup.id);
  const totalGroupSpend = groupExpenses.reduce((s, e) => s + e.amount, 0);

  // Group members
  const members = (activeGroup.members || []).map((m) => {
    const user = allUsers.find((u) => u.id === m.userId);
    return {
      ...user,
      role: m.role || 'Member',
    };
  }).filter(Boolean);

  // Filtered expenses
  const displayedExpenses = groupExpenses.filter((e) => {
    if (filter === 'MINE') {
      return e.paidBy === currentUser.id || e.splitDetails?.some((s) => s.userId === currentUser.id);
    }
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Group Header Card */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 text-white flex items-center justify-center font-extrabold text-2xl shadow-md shadow-blue-500/20">
              {activeGroup.name.charAt(0)}
            </div>

            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-extrabold text-slate-900 dark:text-white tracking-tight">
                  {activeGroup.name}
                </h2>
                <Badge variant="paypal" size="sm">
                  {activeGroup.category}
                </Badge>
              </div>

              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xl">
                {activeGroup.description || 'Shared expense tracking'}
              </p>

              {/* Members chip row */}
              <div className="flex flex-wrap items-center gap-2 mt-3">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mr-1">
                  Members:
                </span>
                {members.map((member) => (
                  <div
                    key={member.id}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-medium"
                  >
                    <img
                      src={member.avatar}
                      alt={member.name}
                      className="w-4 h-4 rounded-full object-cover"
                    />
                    <span>{member.name.split(' ')[0]}</span>
                    {member.id === currentUser.id && (
                      <span className="text-[10px] text-blue-600 dark:text-blue-400 font-bold">(You)</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="flex flex-wrap items-center gap-2.5">
            <Button
              variant="paypal"
              size="md"
              icon={ScanLine}
              onClick={onScanReceipt}
            >
              Scan Receipt
            </Button>
            <Button
              variant="outline"
              size="md"
              icon={Plus}
              onClick={onAddExpense}
            >
              Add Expense
            </Button>
          </div>
        </div>

        {/* Group Spending Overview Strip */}
        <div className="mt-6 pt-5 border-t border-slate-100 dark:border-slate-800 grid grid-cols-2 sm:grid-cols-3 gap-4 text-center sm:text-left">
          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Total Group Spend
            </span>
            <span className="text-xl font-extrabold text-slate-900 dark:text-white mt-0.5 block">
              ${totalGroupSpend.toFixed(2)}
            </span>
          </div>

          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Total Bills Recorded
            </span>
            <span className="text-xl font-extrabold text-slate-900 dark:text-white mt-0.5 block">
              {groupExpenses.length}
            </span>
          </div>

          <div className="col-span-2 sm:col-span-1">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Settlement Method
            </span>
            <span className="text-xs font-semibold text-[#0070BA] dark:text-blue-400 mt-1 flex items-center justify-center sm:justify-start gap-1">
              <ShieldCheck className="w-4 h-4" />
              PayPal Sandbox Automated
            </span>
          </div>
        </div>
      </div>

      {/* Group Expenses List */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-100 dark:border-slate-800">
          <div>
            <h3 className="text-base font-bold text-slate-900 dark:text-white">
              Group Expenses & Receipts
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Click any bill to view itemized split calculations
            </p>
          </div>

          <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-1 rounded-xl">
            <button
              onClick={() => setFilter('ALL')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                filter === 'ALL'
                  ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-xs'
                  : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              All ({groupExpenses.length})
            </button>
            <button
              onClick={() => setFilter('MINE')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                filter === 'MINE'
                  ? 'bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-400 shadow-xs'
                  : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              My Shares
            </button>
          </div>
        </div>

        {displayedExpenses.length === 0 ? (
          <div className="py-12 text-center text-slate-400">
            <Receipt className="w-10 h-10 mx-auto mb-2 opacity-50" />
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              No expenses in this group yet
            </p>
            <p className="text-xs mt-1">
              Click 'Scan Receipt' or 'Add Expense' to get started.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {displayedExpenses.map((expense) => {
              const payer = allUsers.find((u) => u.id === expense.paidBy);
              const isPaidByMe = expense.paidBy === currentUser.id;
              const mySplit = expense.splitDetails?.find((s) => s.userId === currentUser.id);

              return (
                <div
                  key={expense.id}
                  onClick={() => onSelectExpense && onSelectExpense(expense)}
                  className="py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-slate-50/70 dark:hover:bg-slate-800/40 rounded-xl px-3 transition-colors cursor-pointer group"
                >
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-950/60 text-[#0070BA] dark:text-blue-400 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
                      <Receipt className="w-5 h-5" />
                    </div>

                    <div>
                      <h4 className="text-sm font-bold text-slate-900 dark:text-white leading-tight">
                        {expense.description}
                      </h4>

                      <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-slate-500 dark:text-slate-400">
                        <span>
                          Paid by{' '}
                          <span className="font-semibold text-slate-700 dark:text-slate-300">
                            {isPaidByMe ? 'You' : payer?.name}
                          </span>
                        </span>
                        <span>•</span>
                        <span>{expense.date}</span>
                        <span>•</span>
                        <Badge
                          variant={expense.splitType === 'ITEMIZED' ? 'purple' : 'default'}
                          size="sm"
                        >
                          {expense.splitType === 'ITEMIZED' ? 'AI Itemized' : 'Equal Split'}
                        </Badge>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between sm:justify-end gap-4">
                    <div className="text-left sm:text-right">
                      <p className="text-sm font-bold text-slate-900 dark:text-white">
                        ${expense.amount.toFixed(2)}
                      </p>
                      {mySplit && (
                        <p className={`text-xs font-semibold ${
                          isPaidByMe ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'
                        }`}>
                          {isPaidByMe
                            ? `You lent $${(expense.amount - mySplit.share).toFixed(2)}`
                            : `Your share: $${mySplit.share.toFixed(2)}`}
                        </p>
                      )}
                    </div>

                    <ArrowRight className="w-4 h-4 text-slate-400 group-hover:text-blue-600 dark:group-hover:text-blue-400 group-hover:translate-x-1 transition-all" />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

