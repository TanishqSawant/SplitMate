import React, { useState } from 'react';
import { Sparkles, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { useAuth } from '../../context/AuthContext';
import Button from '../common/Button';

export default function ItemSplitAssignment({ onFinalized }) {
  const {
    receiptScan,
    groups,
    activeGroup,
    finalizeReceiptScan,
  } = useExpenses();
  const { currentUser, allUsers } = useAuth();

  const [selectedGroupId, setSelectedGroupId] = useState(activeGroup?.id || groups[0]?.id);
  const [paidByUserId, setPaidByUserId] = useState(currentUser?.id);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const data = receiptScan.extractedData;
  if (!data) return null;

  const isCompleted = receiptScan.extractionStatus === 'completed' || data.extractionStatus === 'completed';
  const isReviewRequired = receiptScan.extractionStatus === 'review_required' || data.extractionStatus === 'review_required';

  const currentSelectedGroup = groups.find((g) => g.id === selectedGroupId) || activeGroup;
  const groupMembers = currentSelectedGroup?.members
    ? currentSelectedGroup.members.map((m) => {
        // Handle both mock structure (userId) and backend structure (user_id)
        const uid = m.userId || m.user_id;
        return allUsers.find((u) => u.id === uid);
      }).filter(Boolean)
    : allUsers;

  // Real-time calculation of member shares including pro-rated tax and tip
  const memberBreakdown = groupMembers.map((member) => {
    let rawItemShare = 0;
    (data.items || []).forEach((item) => {
      const assigned = item.assignedTo || [];
      if (assigned.includes(member.id) && item.price != null) {
        rawItemShare += item.price / assigned.length;
      }
    });

    const itemsTotal = (data.items || []).reduce((s, it) => s + (it.price != null ? it.price : 0), 0);
    const extraCharges = (data.tax || 0) + (data.tip || 0);
    const ratio = itemsTotal > 0 ? rawItemShare / itemsTotal : 0;
    const finalShare = rawItemShare + extraCharges * ratio;

    return {
      member,
      rawItemShare,
      finalShare: Number(finalShare.toFixed(2)),
    };
  });

  const handleFinalize = async () => {
    if (!isCompleted) return;
    setIsSubmitting(true);
    try {
      await finalizeReceiptScan(selectedGroupId, paidByUserId);
      if (onFinalized) onFinalized();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-5">
      <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
        <div>
          <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
            Split Finalization & Assignment
          </h4>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Select group and payer to calculate exact debits
          </p>
        </div>

        <span className={`text-lg font-black ${data.total != null ? 'text-blue-600 dark:text-blue-400' : 'text-amber-500'}`}>
          {data.total != null
            ? `${data.currency ? data.currency + ' ' : '$'}${Number(data.total).toFixed(2)}`
            : 'Total Missing'}
        </span>
      </div>

      {/* Target Group & Payer Selectors */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
            Assign to Group
          </label>
          <select
            value={selectedGroupId}
            onChange={(e) => setSelectedGroupId(e.target.value)}
            className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          >
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name} ({group.members?.length || 0} members)
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
            Who Paid the Bill?
          </label>
          <select
            value={paidByUserId}
            onChange={(e) => setPaidByUserId(e.target.value)}
            className="w-full px-3 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          >
            {groupMembers.map((member) => (
              <option key={member.id} value={member.id}>
                {member.name} {member.id === currentUser?.id ? '(You)' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Real-time Calculated Shares Table */}
      <div className="space-y-2">
        <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
          Calculated Individual Shares (Items + Pro-Rated Tax & Tip)
        </label>

        <div className="rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800 overflow-hidden">
          {memberBreakdown.map(({ member, finalShare }) => {
            const isPayer = member.id === paidByUserId;
            return (
              <div
                key={member.id}
                className="flex items-center justify-between px-4 py-2.5 bg-slate-50/50 dark:bg-slate-800/40 text-xs"
              >
                <div className="flex items-center gap-2.5">
                  <img
                    src={member.avatar}
                    alt={member.name}
                    className="w-6 h-6 rounded-full object-cover"
                  />
                  <span className="font-semibold text-slate-900 dark:text-white">
                    {member.name}
                  </span>
                  {isPayer && (
                    <span className="text-[10px] bg-blue-100 text-blue-700 dark:bg-blue-900/60 dark:text-blue-300 px-2 py-0.5 rounded-full font-bold">
                      Paid Bill
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-slate-900 dark:text-white">
                    ${finalShare.toFixed(2)}
                  </span>
                  {!isPayer && (
                    <span className="text-[11px] text-slate-400">
                      owes {groupMembers.find((m) => m.id === paidByUserId)?.name?.split(' ')[0]}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Completion Gate Warning Notice */}
      {!isCompleted && (
        <div className="p-3.5 rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-950/30 text-amber-900 dark:text-amber-200 text-xs flex items-center gap-2.5">
          <AlertCircle className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <span>
            Human review is required before this expense can be finalized or settled. Please submit your review corrections in the section above to complete extraction.
          </span>
        </div>
      )}

      {/* Submit Button */}
      <Button
        variant={isCompleted ? "primary" : "secondary"}
        size="lg"
        icon={Sparkles}
        isLoading={isSubmitting}
        disabled={!isCompleted || isSubmitting}
        onClick={handleFinalize}
        className={`w-full py-3 text-base ${
          isCompleted
            ? 'bg-gradient-to-r from-blue-600 via-indigo-600 to-[#0070BA] hover:from-blue-700 hover:to-blue-800 shadow-md'
            : 'opacity-60 cursor-not-allowed bg-slate-200 dark:bg-slate-800 text-slate-500 dark:text-slate-400'
        }`}
      >
        {isCompleted ? 'Confirm & Split with Squad' : 'Complete Receipt Review First'}
      </Button>
    </div>
  );
}
