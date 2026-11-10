import React, { useState } from 'react';
import { useExpenses } from '../context/ExpenseContext';
import GroupList from '../components/expenses/GroupList';
import GroupDetail from '../components/expenses/GroupDetail';
import CreateGroupModal from '../components/expenses/CreateGroupModal';
import AddExpenseModal from '../components/expenses/AddExpenseModal';

export default function GroupsView({
  onScanReceipt,
  onSelectExpense,
}) {
  const { setActiveGroup } = useExpenses();
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isAddExpenseOpen, setIsAddExpenseOpen] = useState(false);

  return (
    <div className="space-y-8 animate-in fade-in duration-150">
      {/* 1. Group Selector Strip */}
      <GroupList
        onSelectGroup={(group) => setActiveGroup(group)}
        onCreateGroup={() => setIsCreateModalOpen(true)}
      />

      {/* 2. Detailed View of Active Group */}
      <GroupDetail
        onAddExpense={() => setIsAddExpenseOpen(true)}
        onScanReceipt={onScanReceipt}
        onSelectExpense={onSelectExpense}
      />

      {/* Modals */}
      <CreateGroupModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
      />

      <AddExpenseModal
        isOpen={isAddExpenseOpen}
        onClose={() => setIsAddExpenseOpen(false)}
      />
    </div>
  );
}
