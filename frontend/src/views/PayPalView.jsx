import React from 'react';
import {
  CreditCard,
  ShieldCheck,
  CheckCircle2,
  Lock,
  ArrowRight,
  ExternalLink,
  Copy,
  Receipt,
  FileCheck
} from 'lucide-react';
import { useExpenses } from '../context/ExpenseContext';
import { useAuth } from '../context/AuthContext';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';

export default function PayPalView() {
  const { debtBreakdown, transactions, openPayPalPayment } = useExpenses();
  const { currentUser } = useAuth();

  const myDebts = debtBreakdown.filter((d) => d.isCurrentUserDebtor);
  const owedToMe = debtBreakdown.filter((d) => d.isCurrentUserCreditor);

  return (
    <div className="space-y-6 animate-in fade-in duration-150">
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-[#003087] via-[#0070BA] to-sky-600 rounded-2xl p-6 text-white shadow-lg relative overflow-hidden">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="max-w-xl">
            <div className="flex items-center gap-2 mb-2">
              <Badge variant="paypal" size="sm" className="bg-white text-[#003087]">
                <ShieldCheck className="w-3.5 h-3.5" />
                PayPal Sandbox Payments
              </Badge>
              <span className="text-xs text-sky-100">Tanay's Integration Module</span>
            </div>
            <h2 className="text-2xl font-extrabold tracking-tight text-white">
              Instant Peer-to-Peer Balance Settlement
            </h2>
            <p className="text-xs text-blue-100/90 mt-1 leading-relaxed">
              Settle group debts securely in real time. Transactions are authorized and captured
              via PayPal Sandbox endpoints, updating squad balances immediately with zero duplicate charges.
            </p>
          </div>

          <div className="bg-white/10 backdrop-blur-md rounded-xl p-4 border border-white/20 text-xs space-y-1">
            <p className="font-semibold text-white">Connected Sandbox Account:</p>
            <p className="font-mono text-sky-200 text-[11px] truncate">{currentUser?.paypalEmail}</p>
            <div className="flex items-center gap-1.5 text-emerald-300 font-semibold pt-1">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Sandbox Ready</span>
            </div>
          </div>
        </div>
      </div>

      {/* Pending Balances Ready to Settle */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Debts You Owe */}
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-white">
                Debts You Owe
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Pay teammates instantly with PayPal Sandbox
              </p>
            </div>
            <span className="text-sm font-extrabold text-rose-600 dark:text-rose-400">
              {myDebts.length} Pending
            </span>
          </div>

          {myDebts.length === 0 ? (
            <div className="py-8 text-center text-slate-400">
              <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto mb-2" />
              <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                You owe nothing! All your balances are settled.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {myDebts.map((debt) => (
                <div
                  key={debt.id}
                  className="p-3.5 rounded-xl border border-rose-100 dark:border-rose-950/50 bg-rose-50/30 dark:bg-rose-950/20 flex items-center justify-between gap-3"
                >
                  <div className="flex items-center gap-3">
                    <img
                      src={debt.creditor.avatar}
                      alt={debt.creditor.name}
                      className="w-10 h-10 rounded-xl object-cover"
                    />
                    <div>
                      <p className="text-xs font-bold text-slate-900 dark:text-white">
                        {debt.creditor.name}
                      </p>
                      <p className="text-[11px] font-mono text-slate-400">
                        {debt.creditor.paypalEmail}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-base font-black text-rose-600 dark:text-rose-400">
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
                      Pay Now
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Money Owed to You */}
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-white">
                Money Owed to You
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Awaiting PayPal settlement from squad members
              </p>
            </div>
            <span className="text-sm font-extrabold text-emerald-600 dark:text-emerald-400">
              {owedToMe.length} Incoming
            </span>
          </div>

          {owedToMe.length === 0 ? (
            <div className="py-8 text-center text-slate-400">
              <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                No incoming payments pending
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {owedToMe.map((debt) => (
                <div
                  key={debt.id}
                  className="p-3.5 rounded-xl border border-emerald-100 dark:border-emerald-950/50 bg-emerald-50/30 dark:bg-emerald-950/20 flex items-center justify-between gap-3"
                >
                  <div className="flex items-center gap-3">
                    <img
                      src={debt.debtor.avatar}
                      alt={debt.debtor.name}
                      className="w-10 h-10 rounded-xl object-cover"
                    />
                    <div>
                      <p className="text-xs font-bold text-slate-900 dark:text-white">
                        {debt.debtor.name}
                      </p>
                      <p className="text-[11px] text-slate-400">
                        {debt.debtor.paypalEmail}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-base font-black text-emerald-600 dark:text-emerald-400">
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
      </div>

      {/* PayPal Sandbox Transaction Log */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
          <div>
            <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <FileCheck className="w-5 h-5 text-emerald-600" />
              Completed PayPal Sandbox Settlements
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Verified captures recorded via PayPal Sandbox API
            </p>
          </div>

          <Badge variant="paypal" size="sm">
            {transactions.length} Verified
          </Badge>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-400 font-semibold uppercase tracking-wider text-[10px]">
                <th className="pb-3 pl-2">PayPal Capture ID</th>
                <th className="pb-3">Payer & Receiver</th>
                <th className="pb-3">Date</th>
                <th className="pb-3">Amount</th>
                <th className="pb-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {transactions.map((txn) => (
                <tr key={txn.id} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/40">
                  <td className="py-3 pl-2 font-mono text-blue-600 dark:text-blue-400 font-semibold">
                    {txn.captureId || txn.id}
                  </td>
                  <td className="py-3">
                    <span className="font-semibold text-slate-900 dark:text-white">
                      {txn.payerName}
                    </span>
                    <span className="text-slate-400 mx-1.5">→</span>
                    <span className="font-semibold text-slate-900 dark:text-white">
                      {txn.receiverName}
                    </span>
                  </td>
                  <td className="py-3 text-slate-400 font-mono">
                    {new Date(txn.date).toLocaleDateString()}
                  </td>
                  <td className="py-3 font-mono font-bold text-slate-900 dark:text-white">
                    ${txn.amount.toFixed(2)}
                  </td>
                  <td className="py-3">
                    <Badge variant="success" size="sm">
                      {txn.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
