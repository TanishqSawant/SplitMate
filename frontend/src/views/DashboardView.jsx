import React from 'react';
import MetricCards from '../components/dashboard/MetricCards';
import QuickActions from '../components/dashboard/QuickActions';
import PendingSettlements from '../components/dashboard/PendingSettlements';
import RecentActivity from '../components/dashboard/RecentActivity';
import CategoryBreakdown from '../components/analytics/CategoryBreakdown';

export default function DashboardView({
  onNavigate,
  onScanReceipt,
  onAddExpense,
  onCreateGroup,
  onLoadSampleReceipt,
  onSelectExpense,
}) {
  return (
    <div className="space-y-6 animate-in fade-in duration-150">
      {/* Top Banner & Quick Actions */}
      <QuickActions
        onScanReceipt={onScanReceipt}
        onAddExpense={onAddExpense}
        onCreateGroup={onCreateGroup}
        onLoadSampleReceipt={onLoadSampleReceipt}
      />

      {/* Financial Overview Metric Cards */}
      <MetricCards onNavigate={onNavigate} />

      {/* Middle Grid: Settlements & Spending Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <PendingSettlements onNavigate={onNavigate} />
          <RecentActivity
            onNavigate={onNavigate}
            onSelectExpense={onSelectExpense}
          />
        </div>

        <div className="space-y-6">
          <CategoryBreakdown />
        </div>
      </div>
    </div>
  );
}

