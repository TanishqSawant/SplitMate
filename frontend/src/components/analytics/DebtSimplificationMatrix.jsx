import React from 'react';
import { Share2, Zap, ArrowRight, CheckCircle2, CreditCard } from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { useAuth } from '../../context/AuthContext';
import Button from '../common/Button';
import Badge from '../common/Badge';

export default function DebtSimplificationMatrix() {
  const { debtBreakdown, openPayPalPayment } = useExpenses();
  const { currentUser } = useAuth();

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <Share2 className="w-4 h-4 text-[#0070BA]" />
              AI Debt Simplification Engine
            </h3>
            <Badge variant="paypal" size="sm">
              <Zap className="w-3 h-3 fill-current" />
              Graph Optimized
            </Badge>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Minimizes total number of transactions required to settle group balances
          </p>
        </div>

        <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/60 px-2.5 py-1 rounded-full border border-emerald-200 dark:border-emerald-800 flex items-center gap-1.5">
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span>Optimized to {debtBreakdown.length} direct transfers</span>
        </div>
      </div>

      {debtBreakdown.length === 0 ? (
        <div className="py-8 text-center text-slate-400">
          <CheckCircle2 className="w-10 h-10 mx-auto mb-2 text-emerald-500" />
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
            Zero outstanding debts
          </p>
          <p className="text-xs text-slate-400 mt-0.5">
            All group members are settled up!
          </p>
        </div>
      ) : (
        <div className="space-y-3 pt-2">
          {debtBreakdown.map((debt) => {
            const isMeDebtor = debt.isCurrentUserDebtor;
            const isMeCreditor = debt.isCurrentUserCreditor;

            return (
              <div
                key={debt.id}
                className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 gap-3"
              >
                {/* Transfer Diagram */}
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <img
                      src={debt.debtor.avatar}
                      alt={debt.debtor.name}
                      className="w-8 h-8 rounded-full object-cover ring-2 ring-rose-200 dark:ring-rose-900"
                    />
                    <div className="text-left">
                      <span className="text-xs font-bold text-slate-900 dark:text-white block">
                        {debt.debtor.name}
                      </span>
                      <span className="text-[10px] text-slate-400 block">Debtor</span>
                    </div>
                  </div>

                  <div className="flex flex-col items-center px-2">
                    <span className="text-xs font-mono font-bold text-[#0070BA] dark:text-blue-400">
                      ${debt.amount.toFixed(2)}
                    </span>
                    <ArrowRight className="w-4 h-4 text-slate-400" />
                  </div>

                  <div className="flex items-center gap-2">
                    <img
                      src={debt.creditor.avatar}
                      alt={debt.creditor.name}
                      className="w-8 h-8 rounded-full object-cover ring-2 ring-emerald-200 dark:ring-emerald-900"
                    />
                    <div className="text-left">
                      <span className="text-xs font-bold text-slate-900 dark:text-white block">
                        {debt.creditor.name}
                      </span>
                      <span className="text-[10px] text-slate-400 block">Receiver</span>
                    </div>
                  </div>
                </div>

                {/* Action Button */}
                <div className="flex items-center justify-end gap-2">
                  {isMeDebtor ? (
                    <Button
                      variant="paypal"
                      size="sm"
                      icon={CreditCard}
                      onClick={() =>
                        openPayPalPayment({
                          creditor: debt.creditor,
                          debtor: currentUser,
                          amount: debt.amount,
                          note: `Settling balance with ${debt.creditor.name}`,
                        })
                      }
                    >
                      Pay with PayPal
                    </Button>
                  ) : isMeCreditor ? (
                    <Badge variant="success" size="sm">
                      Awaiting Payment
                    </Badge>
                  ) : (
                    <span className="text-[11px] text-slate-400">
                      Peer-to-peer settlement
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
