import React from 'react';
import { CreditCard, CheckCircle2, ArrowRight, ShieldCheck, AlertCircle } from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { useAuth } from '../../context/AuthContext';
import Button from '../common/Button';
import Badge from '../common/Badge';

export default function PendingSettlements({ onNavigate }) {
  const { debtBreakdown, openPayPalPayment } = useExpenses();
  const { currentUser } = useAuth();

  // Filter debts involving currentUser
  const myDebts = debtBreakdown.filter((d) => d.isCurrentUserDebtor);
  const owedToMe = debtBreakdown.filter((d) => d.isCurrentUserCreditor);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <span>PayPal Settle Up Center</span>
            <Badge variant="paypal" size="sm">
              Instant
            </Badge>
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Real-time balance settlement using PayPal Sandbox
          </p>
        </div>

        <button
          onClick={() => onNavigate('paypal')}
          className="text-xs font-semibold text-[#0070BA] dark:text-blue-400 hover:underline flex items-center gap-1"
        >
          View all settlements
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>

      {myDebts.length === 0 && owedToMe.length === 0 ? (
        <div className="py-8 text-center">
          <div className="w-12 h-12 rounded-full bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 mx-auto flex items-center justify-center mb-2">
            <CheckCircle2 className="w-6 h-6" />
          </div>
          <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">
            All settled up!
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto">
            You don't owe anyone and no one owes you in your active groups.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Debts you owe */}
          {myDebts.map((debt) => (
            <div
              key={debt.id}
              className="flex items-center justify-between p-3.5 rounded-xl border border-rose-100 dark:border-rose-950/50 bg-rose-50/40 dark:bg-rose-950/20"
            >
              <div className="flex items-center gap-3">
                <img
                  src={debt.creditor.avatar}
                  alt={debt.creditor.name}
                  className="w-10 h-10 rounded-xl object-cover ring-2 ring-white dark:ring-slate-800"
                />
                <div>
                  <p className="text-xs font-semibold text-slate-900 dark:text-white">
                    You owe <span className="font-bold text-rose-600 dark:text-rose-400">{debt.creditor.name}</span>
                  </p>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1 mt-0.5">
                    <span className="font-mono text-slate-400">{debt.creditor.paypalEmail}</span>
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-base font-bold text-rose-600 dark:text-rose-400">
                  ${debt.amount.toFixed(2)}
                </span>
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
              </div>
            </div>
          ))}

          {/* Money owed to you */}
          {owedToMe.map((debt) => (
            <div
              key={debt.id}
              className="flex items-center justify-between p-3.5 rounded-xl border border-emerald-100 dark:border-emerald-950/50 bg-emerald-50/40 dark:bg-emerald-950/20"
            >
              <div className="flex items-center gap-3">
                <img
                  src={debt.debtor.avatar}
                  alt={debt.debtor.name}
                  className="w-10 h-10 rounded-xl object-cover ring-2 ring-white dark:ring-slate-800"
                />
                <div>
                  <p className="text-xs font-semibold text-slate-900 dark:text-white">
                    <span className="font-bold text-emerald-600 dark:text-emerald-400">{debt.debtor.name}</span> owes you
                  </p>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                    Pending payment via PayPal
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-base font-bold text-emerald-600 dark:text-emerald-400">
                  +${debt.amount.toFixed(2)}
                </span>
                <Badge variant="success" size="sm">
                  Requested
                </Badge>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

