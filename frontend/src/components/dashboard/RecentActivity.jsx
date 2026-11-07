import React from 'react';
import {
  Receipt,
  Utensils,
  ShoppingBag,
  Coffee,
  Plane,
  Home,
  ArrowRight
} from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { MOCK_USERS } from '../../api/mockData';
import Badge from '../common/Badge';

export default function RecentActivity({ onNavigate, onSelectExpense }) {
  const { expenses, groups } = useExpenses();

  const getCategoryIcon = (category) => {
    switch (category) {
      case 'Food & Dining':
        return Utensils;
      case 'Groceries':
        return ShoppingBag;
      case 'Coffee & Snacks':
        return Coffee;
      case 'Travel':
        return Plane;
      case 'Housing':
      case 'Utilities':
        return Home;
      default:
        return Receipt;
    }
  };

  const getPayerName = (userId) => {
    const user = MOCK_USERS.find((u) => u.id === userId);
    return user ? user.name : 'Teammate';
  };

  const getGroupName = (groupId) => {
    const group = groups.find((g) => g.id === groupId);
    return group ? group.name : 'General';
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            Recent Expenses & Splits
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Latest group purchases and AI itemized receipts
          </p>
        </div>

        <button
          onClick={() => onNavigate('transactions')}
          className="text-xs font-semibold text-[#0070BA] dark:text-blue-400 hover:underline flex items-center gap-1"
        >
          View all transactions
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {expenses.slice(0, 5).map((expense) => {
          const CategoryIcon = getCategoryIcon(expense.category);
          const payer = getPayerName(expense.paidBy);
          const groupName = getGroupName(expense.groupId);

          return (
            <div
              key={expense.id}
              onClick={() => onSelectExpense && onSelectExpense(expense)}
              className="py-3.5 flex items-center justify-between hover:bg-slate-50/80 dark:hover:bg-slate-800/40 rounded-xl px-2 transition-colors cursor-pointer group"
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-950/60 text-[#0070BA] dark:text-blue-400 flex items-center justify-center group-hover:scale-105 transition-transform">
                  <CategoryIcon className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-900 dark:text-white leading-tight">
                    {expense.description}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      Paid by <span className="font-medium text-slate-700 dark:text-slate-300">{payer}</span>
                    </span>
                    <span className="text-slate-300 dark:text-slate-700">•</span>
                    <span className="text-xs text-slate-400">{groupName}</span>
                  </div>
                </div>
              </div>

              <div className="text-right">
                <p className="text-sm font-bold text-slate-900 dark:text-white">
                  ${expense.amount.toFixed(2)}
                </p>
                <div className="mt-0.5 flex justify-end gap-1.5">
                  {expense.receiptId && (
                    <Badge variant="purple" size="sm">
                      AI Scanned
                    </Badge>
                  )}
                  <span className="text-[11px] text-slate-400">{expense.date}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
