import React, { useState } from 'react';
import {
  CreditCard,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  Lock,
  ArrowRight,
  ExternalLink,
  Copy,
  Check
} from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import Modal from '../common/Modal';
import Button from '../common/Button';
import Badge from '../common/Badge';

export default function PayPalPaymentModal() {
  const { payPalModal, closePayPalModal, executePayPalPayment } = useExpenses();
  const [copied, setCopied] = useState(false);

  if (!payPalModal.isOpen) return null;

  const { payer, receiver, amount, currency, note, status, transactionId, error, paymentId } = payPalModal;

  const handleCopyId = () => {
    if (transactionId) {
      navigator.clipboard.writeText(transactionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleExecute = () => {
    if (paymentId) {
      executePayPalPayment(paymentId);
    } else {
      console.error('[SplitMate] No payment ID available');
    }
  };

  return (
    <Modal
      isOpen={payPalModal.isOpen}
      onClose={status === 'capturing' || status === 'initiating' ? () => {} : closePayPalModal}
      maxWidth="max-w-md"
      showClose={status !== 'capturing' && status !== 'initiating'}
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
                  {receiver?.name}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">PayPal Account:</span>
                <span className="font-mono text-blue-600 dark:text-blue-400">
                  {receiver?.paypalEmail}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Payment Note:</span>
                <span className="text-slate-700 dark:text-slate-300 italic">
                  {note || 'Group settlement'}
                </span>
              </div>
              <div className="flex justify-between pt-2 border-t border-slate-200 dark:border-slate-700 font-medium">
                <span className="text-slate-500 dark:text-slate-400">PayPal Sandbox Fee:</span>
                <span className="text-emerald-600 dark:text-emerald-400 font-bold">$0.00 (Waived)</span>
              </div>
            </div>

            {/* Yellow PayPal Branded Button */}
            <button
              onClick={handleExecute}
              disabled={!paymentId}
              className="w-full py-3.5 px-6 rounded-2xl bg-[#FFC439] hover:bg-[#F2BA36] text-[#003087] font-black text-base shadow-md hover:shadow-lg transition-all transform active:scale-[0.98] flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span>Pay with</span>
              <span className="italic font-extrabold text-lg tracking-tight">PayPal</span>
            </button>

            <p className="text-[11px] text-center text-slate-400">
              Payments are routed via Tanay's FastAPI Sandbox integration endpoints.
            </p>
          </div>
        )}

        {/* State: PROCESSING / AUTHORIZING / CAPTURING */}
        {(status === 'initiating' || status === 'authorizing' || status === 'capturing') && (
          <div className="py-8 text-center space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-blue-50 dark:bg-blue-950/60 text-[#0070BA] mx-auto flex items-center justify-center animate-pulse">
              <CreditCard className="w-8 h-8" />
            </div>

            <div>
              <h4 className="text-base font-bold text-slate-900 dark:text-white">
                {status === 'initiating' && 'Connecting to PayPal Sandbox...'}
                {status === 'authorizing' && 'Authorizing Payment Order...'}
                {status === 'capturing' && 'Capturing Funds & Updating Ledger...'}
              </h4>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Please do not refresh or close this window.
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
                Payment Successful!
              </h4>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                ${amount?.toFixed(2)} has been transferred to {receiver?.name} via PayPal Sandbox.
              </p>
            </div>

            {/* Receipt Proof Slip */}
            <div className="p-3.5 rounded-xl border border-dashed border-slate-300 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/40 text-left font-mono text-xs space-y-1.5 text-slate-700 dark:text-slate-300">
              <div className="flex justify-between">
                <span>PayPal Capture ID:</span>
                <button
                  onClick={handleCopyId}
                  className="font-bold text-blue-600 dark:text-blue-400 flex items-center gap-1 hover:underline"
                >
                  {transactionId}
                  {copied ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                </button>
              </div>
              <div className="flex justify-between">
                <span>Timestamp:</span>
                <span>{new Date().toLocaleTimeString()}</span>
              </div>
              <div className="flex justify-between">
                <span>Status:</span>
                <span className="text-emerald-600 font-bold">COMPLETED</span>
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

        {/* State: ERROR */}
        {status === 'error' && (
          <div className="py-4 text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 mx-auto flex items-center justify-center">
              <AlertCircle className="w-9 h-9" />
            </div>

            <div>
              <h4 className="text-lg font-bold text-slate-900 dark:text-white">
                Payment Could Not Be Completed
              </h4>
              <p className="text-xs text-rose-600 dark:text-rose-400 mt-1">
                {error || 'An error occurred during sandbox payment capture.'}
              </p>
            </div>

            <div className="flex gap-2">
              <Button variant="ghost" size="md" onClick={closePayPalModal} className="flex-1">
                Cancel
              </Button>
              <Button variant="paypal" size="md" onClick={handleExecute} className="flex-1" disabled={!paymentId}>
                Retry Payment
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

