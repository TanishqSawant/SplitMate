import React from 'react';
import {
  ScanLine,
  PlusCircle,
  CreditCard,
  UserPlus,
  Sparkles,
  Zap
} from 'lucide-react';
import Button from '../common/Button';

export default function QuickActions({
  onScanReceipt,
  onAddExpense,
  onCreateGroup,
  onSettlePayPal,
  onLoadSampleReceipt,
}) {
  return (
    <div className="bg-gradient-to-r from-blue-900 via-indigo-900 to-slate-900 rounded-2xl p-6 text-white shadow-lg relative overflow-hidden">
      {/* Subtle decorative glow */}
      <div className="absolute -right-10 -top-10 w-64 h-64 bg-blue-500/20 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute right-40 -bottom-10 w-48 h-48 bg-amber-400/10 rounded-full blur-2xl pointer-events-none" />

      <div className="relative z-10 flex flex-col lg:flex-row lg:items-center justify-between gap-6">
        <div className="max-w-xl">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider bg-amber-400 text-slate-900 flex items-center gap-1 shadow-xs">
              <Zap className="w-3 h-3 fill-current" />
              AI Powered
            </span>
            <span className="text-xs text-blue-200">Zero manual typing required</span>
          </div>
          <h2 className="text-2xl font-extrabold tracking-tight text-white">
            Snap your bill. Let AI extract & split. Settle via PayPal.
          </h2>
          <p className="text-sm text-blue-100/80 mt-1.5 leading-relaxed">
            Upload any dining, grocery, or travel receipt. Pawan's vision OCR extracts line items,
            tax, and totals so you can assign items to friends in seconds.
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            variant="paypal"
            size="lg"
            icon={ScanLine}
            onClick={onScanReceipt}
            className="shadow-md"
          >
            Scan Receipt
          </Button>

          <Button
            variant="primary"
            size="lg"
            icon={PlusCircle}
            onClick={onAddExpense}
            className="bg-white/10 hover:bg-white/20 text-white border border-white/20 backdrop-blur-xs"
          >
            Add Expense
          </Button>

          <Button
            variant="primary"
            size="lg"
            icon={Sparkles}
            onClick={() => onLoadSampleReceipt('rcpt_bistro')}
            className="bg-blue-600/80 hover:bg-blue-600 text-white"
          >
            Try Bistro Demo
          </Button>
        </div>
      </div>
    </div>
  );
}

