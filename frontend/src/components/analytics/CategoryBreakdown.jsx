import React from 'react';
import { PieChart } from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';

export default function CategoryBreakdown() {
  const { expenses } = useExpenses();

  const total = expenses.reduce((sum, e) => sum + e.amount, 0);

  // Group by category
  const categoryMap = {};
  expenses.forEach((e) => {
    const cat = e.category || 'Other';
    categoryMap[cat] = (categoryMap[cat] || 0) + e.amount;
  });

  const categories = Object.keys(categoryMap).map((cat) => ({
    name: cat,
    amount: categoryMap[cat],
    percentage: total > 0 ? (categoryMap[cat] / total) * 100 : 0,
  })).sort((a, b) => b.amount - a.amount);

  const colors = [
    'bg-blue-600',
    'bg-emerald-500',
    'bg-purple-600',
    'bg-amber-500',
    'bg-rose-500',
    'bg-cyan-500',
  ];

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <PieChart className="w-4 h-4 text-blue-600" />
            Spending by Category
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Breakdown across all squad expenses
          </p>
        </div>

        <span className="text-sm font-extrabold text-slate-900 dark:text-white">
          ${total.toFixed(2)} Total
        </span>
      </div>

      {/* Stacked Progress Bar */}
      <div className="w-full h-3 bg-slate-100 dark:bg-slate-800 rounded-full flex overflow-hidden">
        {categories.map((cat, i) => (
          <div
            key={cat.name}
            className={`${colors[i % colors.length]} transition-all duration-500`}
            style={{ width: `${cat.percentage}%` }}
            title={`${cat.name}: $${cat.amount.toFixed(2)} (${cat.percentage.toFixed(1)}%)`}
          />
        ))}
      </div>

      {/* Category List */}
      <div className="space-y-2.5 pt-2">
        {categories.map((cat, i) => (
          <div key={cat.name} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${colors[i % colors.length]}`} />
              <span className="font-medium text-slate-700 dark:text-slate-300">
                {cat.name}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="font-mono font-bold text-slate-900 dark:text-white">
                ${cat.amount.toFixed(2)}
              </span>
              <span className="text-[11px] text-slate-400 w-10 text-right">
                {cat.percentage.toFixed(0)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

