import React, { useState } from 'react';
import {
  Search,
  Sparkles,
  Download
} from 'lucide-react';
import { useExpenses } from '../context/ExpenseContext';
import { useAuth } from '../context/AuthContext';
import Badge from '../components/common/Badge';
import Button from '../components/common/Button';

export default function TransactionsView({ onSelectExpense }) {
  const { expenses, groups } = useExpenses();
  const { allUsers } = useAuth();

  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState('ALL'); // 'ALL' | 'AI' | 'EQUAL'

  const filteredExpenses = expenses.filter((exp) => {
    const matchesSearch =
      exp.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
      exp.category.toLowerCase().includes(searchTerm.toLowerCase());

    if (!matchesSearch) return false;

    if (filterType === 'AI') return exp.splitType === 'ITEMIZED';
    if (filterType === 'EQUAL') return exp.splitType === 'EQUAL';
    return true;
  });

  const handleExportCSV = () => {
    const headers = 'ID,Description,Amount,Category,Date,PaidBy,SplitType\n';
    const rows = filteredExpenses
      .map(
        (e) =>
          `"${e.id}","${e.description}",${e.amount},"${e.category}","${e.date}","${e.paidBy}","${e.splitType}"`
      )
      .join('\n');
    const blob = new Blob([headers + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `splitmate_expenses_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-6 animate-in fade-in duration-150">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-100 dark:border-slate-800">
        <div>
          <h2 className="text-xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Transaction Ledger & History
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Full record of all group expenses, itemized AI splits, and PayPal payments
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          icon={Download}
          onClick={handleExportCSV}
        >
          Export CSV
        </Button>
      </div>

      {/* Search & Filter Controls */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search by description or category..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div className="flex items-center gap-1.5 self-start sm:self-auto">
          <button
            onClick={() => setFilterType('ALL')}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
              filterType === 'ALL'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
            }`}
          >
            All Bills
          </button>

          <button
            onClick={() => setFilterType('AI')}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
              filterType === 'AI'
                ? 'bg-purple-600 text-white shadow-xs'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
            }`}
          >
            <Sparkles className="w-3 h-3" />
            AI Itemized Only
          </button>

          <button
            onClick={() => setFilterType('EQUAL')}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-all ${
              filterType === 'EQUAL'
                ? 'bg-blue-600 text-white shadow-xs'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
            }`}
          >
            Equal Split
          </button>
        </div>
      </div>

      {/* Transaction Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
              <th className="pb-3 pl-2">Expense / Merchant</th>
              <th className="pb-3">Category</th>
              <th className="pb-3">Squad Group</th>
              <th className="pb-3">Paid By</th>
              <th className="pb-3">Date</th>
              <th className="pb-3">Split Method</th>
              <th className="pb-3 pr-2 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {filteredExpenses.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-12 text-center text-slate-400">
                  <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                    No transactions found
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    No expenses match your search query or selected filter.
                  </p>
                </td>
              </tr>
            ) : (
              filteredExpenses.map((exp) => {
              const payer = allUsers.find((u) => u.id === exp.paidBy);
              const group = groups.find((g) => g.id === exp.groupId);

              return (
                <tr
                  key={exp.id}
                  onClick={() => onSelectExpense && onSelectExpense(exp)}
                  className="hover:bg-slate-50/70 dark:hover:bg-slate-800/40 cursor-pointer transition-colors"
                >
                  <td className="py-3 pl-2">
                    <span className="font-bold text-slate-900 dark:text-white">
                      {exp.description}
                    </span>
                  </td>

                  <td className="py-3 text-slate-600 dark:text-slate-300">
                    {exp.category}
                  </td>

                  <td className="py-3 text-slate-500 font-medium">
                    {group?.name || 'Squad'}
                  </td>

                  <td className="py-3">
                    <div className="flex items-center gap-1.5">
                      <img
                        src={payer?.avatar}
                        alt={payer?.name}
                        className="w-5 h-5 rounded-full object-cover"
                      />
                      <span className="text-slate-800 dark:text-slate-200">
                        {payer?.name}
                      </span>
                    </div>
                  </td>

                  <td className="py-3 font-mono text-slate-400">
                    {exp.date}
                  </td>

                  <td className="py-3">
                    <Badge
                      variant={exp.splitType === 'ITEMIZED' ? 'purple' : 'default'}
                      size="sm"
                    >
                      {exp.splitType === 'ITEMIZED' ? 'AI Itemized' : 'Equal Split'}
                    </Badge>
                  </td>

                  <td className="py-3 pr-2 text-right font-mono font-bold text-slate-900 dark:text-white">
                    ${exp.amount.toFixed(2)}
                  </td>
                </tr>
              );
            }))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
