import React from 'react';
import CategoryBreakdown from '../components/analytics/CategoryBreakdown';
import DebtSimplificationMatrix from '../components/analytics/DebtSimplificationMatrix';
import { useExpenses } from '../context/ExpenseContext';

export default function AnalyticsView() {
  const { expenses, groups } = useExpenses();

  const totalSpent = expenses.reduce((s, e) => s + e.amount, 0);
  const avgExpense = expenses.length > 0 ? totalSpent / expenses.length : 0;

  return (
    <div className="space-y-6 animate-in fade-in duration-150">
      {/* Top Analytics Banner */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">
            Cumulative Squad Volume
          </span>
          <span className="text-2xl font-black text-slate-900 dark:text-white mt-1 block">
            ${totalSpent.toFixed(2)}
          </span>
          <span className="text-xs text-slate-400 mt-1 block">
            Across {expenses.length} tracked bills
          </span>
        </div>

        <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">
            Average Bill Size
          </span>
          <span className="text-2xl font-black text-blue-600 dark:text-blue-400 mt-1 block">
            ${avgExpense.toFixed(2)}
          </span>
          <span className="text-xs text-slate-400 mt-1 block">
            Per group receipt
          </span>
        </div>

        <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">
            Active Squads
          </span>
          <span className="text-2xl font-black text-emerald-600 dark:text-emerald-400 mt-1 block">
            {groups.length}
          </span>
          <span className="text-xs text-slate-400 mt-1 block">
            Multi-currency tracking enabled
          </span>
        </div>
      </div>

      {/* Main Charts & Matrix Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CategoryBreakdown />
        <DebtSimplificationMatrix />
      </div>
    </div>
  );
}
