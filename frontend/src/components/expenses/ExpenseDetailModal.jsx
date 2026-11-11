import React from 'react';
import { CreditCard, Sparkles } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useExpenses } from '../../context/ExpenseContext';
import Modal from '../common/Modal';
import Badge from '../common/Badge';
import Button from '../common/Button';

export default function ExpenseDetailModal({ expense, isOpen, onClose }) {
  const { allUsers, currentUser } = useAuth();
  const { groups, openPayPalPayment } = useExpenses();

  if (!expense || !isOpen) return null;

  const payer = allUsers.find((u) => u.id === expense.paidBy);
  const group = groups.find((g) => g.id === expense.groupId);
  const mySplit = expense.splitDetails?.find((s) => s.userId === currentUser.id);

  const canSettle = mySplit && !mySplit.isPaid && expense.paidBy !== currentUser.id;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={expense.description}
      subtitle={`Recorded in ${group?.name || 'Squad'} on ${expense.date}`}
      maxWidth="max-w-lg"
    >
      <div className="space-y-5">
        {/* Top Summary Card */}
        <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Total Amount
            </span>
            <span className="text-2xl font-black text-slate-900 dark:text-white mt-0.5 block">
              ${expense.amount.toFixed(2)}
            </span>
            <span className="text-xs text-slate-500 mt-1 block">
              Paid by <span className="font-semibold text-slate-700 dark:text-slate-300">{payer?.name}</span>
            </span>
          </div>

          <div className="text-right space-y-1">
            <Badge variant={expense.splitType === 'ITEMIZED' ? 'purple' : 'default'} size="sm">
              {expense.splitType === 'ITEMIZED' ? (
                <>
                  <Sparkles className="w-3 h-3" />
                  AI Scanned
                </>
              ) : (
                'Equal Split'
              )}
            </Badge>
            <span className="block text-[11px] text-slate-400">{expense.category}</span>
          </div>
        </div>

        {/* Split Details Table */}
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
            Member Splits Breakdown
          </h4>

          <div className="rounded-xl border border-slate-200 dark:border-slate-800 divide-y divide-slate-100 dark:divide-slate-800 overflow-hidden text-xs">
            {expense.splitDetails?.map((detail) => {
              const member = allUsers.find((u) => u.id === detail.userId);
              const isPayer = detail.userId === expense.paidBy;

              return (
                <div
                  key={detail.userId}
                  className="flex items-center justify-between px-3.5 py-2.5 bg-white dark:bg-slate-900"
                >
                  <div className="flex items-center gap-2.5">
                    <img
                      src={member?.avatar}
                      alt={member?.name}
                      className="w-6 h-6 rounded-full object-cover"
                    />
                    <span className="font-medium text-slate-800 dark:text-slate-200">
                      {member?.name} {member?.id === currentUser.id && '(You)'}
                    </span>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="font-mono font-bold text-slate-900 dark:text-white">
                      ${detail.share.toFixed(2)}
                    </span>
                    {isPayer ? (
                      <Badge variant="primary" size="sm">
                        Payer
                      </Badge>
                    ) : detail.isPaid ? (
                      <Badge variant="success" size="sm">
                        Settled
                      </Badge>
                    ) : (
                      <Badge variant="warning" size="sm">
                        Unpaid
                      </Badge>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Settle Up Action if currentUser owes */}
        {canSettle && (
          <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900 flex items-center justify-between">
            <div>
              <p className="text-xs font-bold text-amber-900 dark:text-amber-200">
                You owe ${mySplit?.share.toFixed(2)} for this bill
              </p>
              <p className="text-[11px] text-amber-700 dark:text-amber-300">
                Settle directly to {payer?.name} via PayPal Sandbox
              </p>
            </div>

            <Button
              variant="paypal"
              size="sm"
              icon={CreditCard}
              onClick={() => {
                onClose();
                openPayPalPayment({
                  creditor: payer,
                  debtor: currentUser,
                  amount: mySplit.share,
                  note: `Settling ${expense.description}`,
                  groupId: expense.groupId,
                  expenseId: expense.id,
                  paymentId: mySplit?.paymentId || null,
                });
              }}
            >
              Pay with PayPal
            </Button>
          </div>
        )}

        <div className="pt-2 flex justify-end">
          <Button variant="ghost" size="md" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
}

