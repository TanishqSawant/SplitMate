import React, { useState } from 'react';
import {
  CreditCard,
  CheckCircle2,
  AlertCircle,
  Lock,
  Copy,
  Check,
  RotateCcw,
  Loader2,
  AlertTriangle
} from 'lucide-react';
import { PayPalButtons, usePayPalScriptReducer } from '@paypal/react-paypal-js';
import { useExpenses } from '../../context/ExpenseContext';
import Modal from '../common/Modal';
import Button from '../common/Button';

export default function PayPalPaymentModal() {
  const {
    payPalModal,
    closePayPalModal,
    createPayPalOrder,
    onApprovePayPalPayment,
    onCancelPayPalPayment,
    handlePayPalError,
    resetPayPalPayment,
  } = useExpenses();

  const [{ isPending, isRejected }] = usePayPalScriptReducer();
  const [copiedTxn, setCopiedTxn] = useState(false);
  const [copiedOrder, setCopiedOrder] = useState(false);
  const [captureTime] = useState(() => new Date().toLocaleTimeString());

  if (!payPalModal.isOpen) return null;

  const {
    receiver,
    amount,
    currency,
    note,
    status,
    orderId,
    transactionId,
    error,
    paymentId,
    expenseId,
  } = payPalModal;

  const handleCopyTxn = () => {
    if (transactionId) {
      navigator.clipboard.writeText(transactionId);
      setCopiedTxn(true);
      setTimeout(() => setCopiedTxn(false), 2000);
    }
  };

  const handleCopyOrder = () => {
    if (orderId) {
      navigator.clipboard.writeText(orderId);
      setCopiedOrder(true);
      setTimeout(() => setCopiedOrder(false), 2000);
    }
  };

  const isBusy = status === 'initiating' || status === 'authorizing' || status === 'capturing';

  return (
    <Modal
      isOpen={payPalModal.isOpen}
      onClose={isBusy ? () => {} : closePayPalModal}
      maxWidth="max-w-md"
      showClose={!isBusy}
    >
      <div className="space-y-5">
        {/* PayPal Sandbox Top Branding */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-[#003087] flex items-center justify-center text-white font-black text-sm">
              P
            </div>
            <div>
              <span className="font-extrabold text-base tracking-tight text-[#003087] dark:text-blue-400">
                PayPal
              </span>
              <span className="text-[10px] font-bold uppercase tracking-wider text-amber-500 ml-1.5 px-1.5 py-0.5 rounded bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-900">
                Sandbox
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1 text-[11px] text-slate-400 font-medium">
            <Lock className="w-3 h-3 text-emerald-500" />
            <span>256-Bit SSL Encrypted</span>
          </div>
        </div>

        {/* State: IDLE / READY TO PAY */}
        {status === 'idle' && (
          <div className="space-y-4">
            <div className="text-center py-2">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">
                Total Settlement Amount
              </span>
              <div className="text-4xl font-black text-slate-900 dark:text-white mt-1">
                ${amount?.toFixed(2)}
                <span className="text-sm font-semibold text-slate-400 ml-1.5">{currency}</span>
              </div>
            </div>

            {/* Recipient Details */}
            <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-800/40 space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Recipient:</span>
                <span className="font-semibold text-slate-900 dark:text-white">
                  {receiver?.name || 'Teammate'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">PayPal Account:</span>
                <span className="font-mono text-blue-600 dark:text-blue-400">
                  {receiver?.paypalEmail || 'sandbox-receiver@splitmate.dev'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Payment Note:</span>
                <span className="text-slate-700 dark:text-slate-300 italic truncate max-w-[200px]">
                  {note || 'Group settlement'}
                </span>
              </div>
              {paymentId && (
                <div className="flex justify-between font-mono text-[11px]">
                  <span className="text-slate-500 dark:text-slate-400">Payment Ref:</span>
                  <span className="text-slate-600 dark:text-slate-400 truncate max-w-[180px]">
                    {paymentId}
                  </span>
                </div>
              )}
              <div className="flex justify-between pt-2 border-t border-slate-200 dark:border-slate-700 font-medium">
                <span className="text-slate-500 dark:text-slate-400">PayPal Sandbox Fee:</span>
                <span className="text-emerald-600 dark:text-emerald-400 font-bold">$0.00 (Waived)</span>
              </div>
            </div>

            {/* Backend payment missing notification if neither paymentId nor expenseId is attached */}
            {!paymentId && !expenseId && (
              <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900 text-xs text-amber-800 dark:text-amber-200 flex items-start gap-2.5">
                <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                <p>
                  This debt is aggregated across group expenses. Real backend capture requires an initialized payment record. Please open the specific expense details to settle with backend synchronization.
                </p>
              </div>
            )}

            {/* Real PayPal Buttons or SDK Loader */}
            <div className="pt-1">
              {isPending ? (
                <div className="py-6 flex flex-col items-center justify-center space-y-2 bg-slate-50 dark:bg-slate-800/30 rounded-2xl border border-dashed border-slate-200 dark:border-slate-700">
                  <Loader2 className="w-6 h-6 text-[#0070BA] animate-spin" />
                  <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                    Connecting to PayPal Sandbox SDK...
                  </span>
                </div>
              ) : isRejected ? (
                <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-center space-y-2">
                  <AlertCircle className="w-6 h-6 text-rose-500 mx-auto" />
                  <p className="text-xs text-rose-700 dark:text-rose-300 font-medium">
                    Failed to initialize PayPal Sandbox SDK. Please verify your internet connection or try again.
                  </p>
                  <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
                    Reload Page
                  </Button>
                </div>
              ) : (
                <PayPalButtons
                  style={{
                    layout: 'vertical',
                    color: 'gold',
                    shape: 'rect',
                    label: 'paypal',
                    height: 48,
                  }}
                  disabled={isBusy}
                  createOrder={async () => {
                    return await createPayPalOrder();
                  }}
                  onApprove={async (data) => {
                    await onApprovePayPalPayment(data.orderID);
                  }}
                  onCancel={() => {
                    onCancelPayPalPayment();
                  }}
                  onError={(err) => {
                    handlePayPalError(err);
                  }}
                />
              )}
            </div>

            <p className="text-[11px] text-center text-slate-400">
              Payments are securely authorized and captured via PayPal Sandbox APIs with zero duplicate charges.
            </p>
          </div>
        )}

        {/* State: PROCESSING / AUTHORIZING / CAPTURING */}
        {isBusy && (
          <div className="py-8 text-center space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-blue-50 dark:bg-blue-950/60 text-[#0070BA] mx-auto flex items-center justify-center animate-pulse shadow-md">
              <CreditCard className="w-8 h-8" />
            </div>

            <div>
              <h4 className="text-base font-bold text-slate-900 dark:text-white">
                {status === 'initiating' && 'Creating PayPal Order on Server...'}
                {status === 'authorizing' && 'Awaiting Authorization in PayPal Window...'}
                {status === 'capturing' && 'Capturing Payment & Updating Ledger...'}
              </h4>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Please do not refresh or close this window while the transaction completes.
              </p>
            </div>

            <div className="w-48 h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full mx-auto overflow-hidden">
              <div className="h-full bg-[#0070BA] rounded-full animate-indeterminate" />
            </div>
          </div>
        )}

        {/* State: SUCCESS */}
        {status === 'success' && (
          <div className="py-4 text-center space-y-4 animate-in fade-in zoom-in-95 duration-200">
            <div className="w-16 h-16 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 mx-auto flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <CheckCircle2 className="w-9 h-9" />
            </div>

            <div>
              <h4 className="text-xl font-extrabold text-slate-900 dark:text-white">
                Payment Captured Successfully!
              </h4>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                ${amount?.toFixed(2)} has been transferred to {receiver?.name || 'recipient'} via PayPal Sandbox.
              </p>
            </div>

            {/* Receipt Proof Slip */}
            <div className="p-3.5 rounded-xl border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/40 text-left font-mono text-xs space-y-2 text-slate-700 dark:text-slate-300">
              <div className="flex justify-between items-center">
                <span>Capture ID:</span>
                <button
                  type="button"
                  onClick={handleCopyTxn}
                  className="font-bold text-blue-600 dark:text-blue-400 flex items-center gap-1 hover:underline cursor-pointer"
                  title="Click to copy Capture ID"
                >
                  <span className="truncate max-w-[180px]">{transactionId}</span>
                  {copiedTxn ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>

              {orderId && (
                <div className="flex justify-between items-center">
                  <span>Order ID:</span>
                  <button
                    type="button"
                    onClick={handleCopyOrder}
                    className="font-bold text-blue-600 dark:text-blue-400 flex items-center gap-1 hover:underline cursor-pointer"
                    title="Click to copy Order ID"
                  >
                    <span className="truncate max-w-[180px]">{orderId}</span>
                    {copiedOrder ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
              )}

              <div className="flex justify-between">
                <span>Timestamp:</span>
                <span>{captureTime}</span>
              </div>
              <div className="flex justify-between">
                <span>Status:</span>
                <span className="text-emerald-600 dark:text-emerald-400 font-bold">CAPTURED & VERIFIED</span>
              </div>
            </div>

            <Button
              variant="primary"
              size="lg"
              onClick={closePayPalModal}
              className="w-full"
            >
              Done & Return to Dashboard
            </Button>
          </div>
        )}

        {/* State: CANCELLED */}
        {status === 'cancelled' && (
          <div className="py-4 text-center space-y-4 animate-in fade-in zoom-in-95 duration-200">
            <div className="w-16 h-16 rounded-full bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 mx-auto flex items-center justify-center shadow-sm">
              <AlertTriangle className="w-9 h-9" />
            </div>

            <div>
              <h4 className="text-lg font-bold text-slate-900 dark:text-white">
                Payment Was Cancelled
              </h4>
              <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                You closed the PayPal window or cancelled the authorization. No funds were transferred.
              </p>
            </div>

            <div className="flex gap-2.5 pt-2">
              <Button variant="ghost" size="md" onClick={closePayPalModal} className="flex-1">
                Close
              </Button>
              <Button
                variant="paypal"
                size="md"
                onClick={resetPayPalPayment}
                icon={RotateCcw}
                className="flex-1"
              >
                Try Again
              </Button>
            </div>
          </div>
        )}

        {/* State: ERROR */}
        {status === 'error' && (
          <div className="py-4 text-center space-y-4 animate-in fade-in zoom-in-95 duration-200">
            <div className="w-16 h-16 rounded-full bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 mx-auto flex items-center justify-center">
              <AlertCircle className="w-9 h-9" />
            </div>

            <div>
              <h4 className="text-lg font-bold text-slate-900 dark:text-white">
                Payment Could Not Be Completed
              </h4>
              <p className="text-xs text-rose-600 dark:text-rose-400 mt-1.5 leading-relaxed bg-rose-50/80 dark:bg-rose-950/50 p-2.5 rounded-xl border border-rose-100 dark:border-rose-900">
                {error || 'An error occurred during sandbox payment capture.'}
              </p>
            </div>

            <div className="flex gap-2.5 pt-1">
              <Button variant="ghost" size="md" onClick={closePayPalModal} className="flex-1">
                Cancel
              </Button>
              <Button
                variant="paypal"
                size="md"
                onClick={resetPayPalPayment}
                icon={RotateCcw}
                className="flex-1"
              >
                Try Again
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
