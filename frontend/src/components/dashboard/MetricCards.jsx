import React from 'react';
import {
  TrendingUp,
  TrendingDown,
  ArrowUpRight,
  ArrowDownLeft,
  DollarSign,
  Wallet,
  Users
} from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { useAuth } from '../../context/AuthContext';

export default function MetricCards({ onNavigate }) {
  const { summary, groups, expenses } = useExpenses();
  const { currentUser } = useAuth();

  const totalGroupSpending = expenses.reduce((sum, e) => sum + e.amount, 0);

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* 1. Net Balance Card */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs relative overflow-hidden group">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
            Net Balance
          </span>
          <div className={`p-2 rounded-xl ${
            summary.netBalance >= 0
              ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400'
              : 'bg-rose-50 text-rose-600 dark:bg-rose-950/60 dark:text-rose-400'
          }`}>
            <Wallet className="w-4 h-4" />
          </div>
        </div>

        <div className="mt-3">
          <div className="flex items-baseline gap-1">
            <span className={`text-2xl font-bold tracking-tight ${
              summary.netBalance >= 0
                ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-rose-600 dark:text-rose-400'
            }`}>
              {summary.netBalance >= 0 ? '+' : '-'}${Math.abs(summary.netBalance).toFixed(2)}
            </span>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            {summary.netBalance >= 0
              ? 'Overall you are owed money'
              : 'Overall you owe money to friends'}
          </p>
        </div>

        <div className={`absolute bottom-0 left-0 right-0 h-1 ${
          summary.netBalance >= 0 ? 'bg-emerald-500' : 'bg-rose-500'
        }`} />
      </div>

      {/* 2. You Are Owed Card */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs relative overflow-hidden group">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
            Owed to You
          </span>
          <div className="p-2 rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
            <ArrowDownLeft className="w-4 h-4" />
          </div>
        </div>

        <div className="mt-3">
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
              ${summary.totalOwedToYou.toFixed(2)}
            </span>
          </div>
          <p className="text-xs text-emerald-600 dark:text-emerald-400 font-medium mt-1 flex items-center gap-1">
            <TrendingUp className="w-3.5 h-3.5" />
            From group split shares
          </p>
        </div>

        <div className="absolute bottom-0 left-0 right-0 h-1 bg-emerald-500" />
      </div>

      {/* 3. You Owe Card */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs relative overflow-hidden group">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
            You Owe
          </span>
          <div className="p-2 rounded-xl bg-rose-50 text-rose-600 dark:bg-rose-950/60 dark:text-rose-400">
            <ArrowUpRight className="w-4 h-4" />
          </div>
        </div>

        <div className="mt-3">
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
              ${summary.totalYouOwe.toFixed(2)}
            </span>
          </div>
          <button
            onClick={() => onNavigate('paypal')}
            className="text-xs text-blue-600 dark:text-blue-400 hover:underline font-medium mt-1 flex items-center gap-1"
          >
            Settle with PayPal Sandbox →
          </button>
        </div>

        <div className="absolute bottom-0 left-0 right-0 h-1 bg-rose-500" />
      </div>

      {/* 4. Active Groups & Total Volume */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs relative overflow-hidden group">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
            Active Groups
          </span>
          <div className="p-2 rounded-xl bg-blue-50 text-[#0070BA] dark:bg-blue-950/60 dark:text-blue-400">
            <Users className="w-4 h-4" />
          </div>
        </div>

        <div className="mt-3">
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
              {groups.length}
            </span>
            <span className="text-xs text-slate-400">
              (${totalGroupSpending.toFixed(2)} total)
            </span>
          </div>
          <button
            onClick={() => onNavigate('groups')}
            className="text-xs text-blue-600 dark:text-blue-400 hover:underline font-medium mt-1 flex items-center gap-1"
          >
            Manage squads & splits →
          </button>
        </div>

        <div className="absolute bottom-0 left-0 right-0 h-1 bg-[#0070BA]" />
      </div>
    </div>
  );
}

