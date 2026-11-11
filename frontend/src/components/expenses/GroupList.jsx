import React from 'react';
import { Plus } from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { useAuth } from '../../context/AuthContext';
import Button from '../common/Button';
import Badge from '../common/Badge';

export default function GroupList({ onSelectGroup, onCreateGroup }) {
  const { groups, activeGroup, expenses } = useExpenses();
  const { allUsers } = useAuth();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            Your Expense Groups
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Organize trips, hackathons, and shared apartment bills
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={Plus}
          onClick={onCreateGroup}
        >
          New Group
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {groups.map((group) => {
          const isSelected = activeGroup?.id === group.id;
          const groupExpenseCount = expenses.filter((e) => e.groupId === group.id).length;
          const totalSpend = expenses
            .filter((e) => e.groupId === group.id)
            .reduce((s, e) => s + e.amount, 0);

          return (
            <div
              key={group.id}
              onClick={() => onSelectGroup(group)}
              className={`p-5 rounded-2xl border transition-all cursor-pointer flex flex-col justify-between ${
                isSelected
                  ? 'border-blue-500 ring-2 ring-blue-500/20 bg-blue-50/20 dark:bg-blue-950/20 shadow-sm'
                  : 'border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700 shadow-xs'
              }`}
            >
              <div>
                <div className="flex items-start justify-between mb-3">
                  <div className="w-10 h-10 rounded-xl bg-blue-100 dark:bg-blue-950/70 text-[#0070BA] dark:text-blue-400 flex items-center justify-center font-bold text-base">
                    {group.name.charAt(0)}
                  </div>
                  <Badge variant="default" size="sm">
                    {group.category}
                  </Badge>
                </div>

                <h4 className="text-sm font-bold text-slate-900 dark:text-white line-clamp-1">
                  {group.name}
                </h4>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-2 leading-relaxed">
                  {group.description || 'Shared expense tracking'}
                </p>

                {/* Member avatars */}
                <div className="flex items-center -space-x-1.5 mt-3">
                  {group.members?.map((m) => {
                    const memberUser = allUsers.find((u) => u.id === m.userId);
                    return (
                      <img
                        key={m.userId}
                        src={memberUser?.avatar || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150'}
                        alt={memberUser?.name || 'Member'}
                        className="w-6 h-6 rounded-full object-cover ring-2 ring-white dark:ring-slate-900"
                        title={memberUser?.name}
                      />
                    );
                  })}
                  <span className="text-[11px] text-slate-400 pl-3">
                    {group.members?.length || 0} members
                  </span>
                </div>
              </div>

              {/* Bottom statistics */}
              <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-xs">
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                    Total Spend
                  </span>
                  <span className="font-bold text-slate-900 dark:text-white">
                    ${totalSpend.toFixed(2)}
                  </span>
                </div>

                <div className="text-right">
                  <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                    Expenses
                  </span>
                  <span className="font-semibold text-slate-700 dark:text-slate-300">
                    {groupExpenseCount} bills
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

