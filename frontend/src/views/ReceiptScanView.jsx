import React from 'react';
import { Sparkles, ArrowLeft, RotateCcw, ShieldCheck } from 'lucide-react';
import { useExpenses } from '../context/ExpenseContext';
import ReceiptUploader from '../components/receipt/ReceiptUploader';
import ReceiptPreview from '../components/receipt/ReceiptPreview';
import ExtractionResult from '../components/receipt/ExtractionResult';
import ItemSplitAssignment from '../components/receipt/ItemSplitAssignment';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';

export default function ReceiptScanView({ onNavigate }) {
  const { receiptScan, resetReceiptScan } = useExpenses();

  const handleReset = () => {
    resetReceiptScan();
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-150">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-extrabold text-slate-900 dark:text-white tracking-tight">
              AI Receipt Extraction & Itemized Splitting
            </h2>
            <Badge variant="purple" size="sm">
              <Sparkles className="w-3 h-3" />
              Pawan's AI Engine
            </Badge>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Extracts line items, dishes, tax, and totals automatically using computer vision OCR
          </p>
        </div>

        {receiptScan.status === 'review' && (
          <Button
            variant="outline"
            size="sm"
            icon={RotateCcw}
            onClick={resetReceiptScan}
          >
            Scan Another Receipt
          </Button>
        )}
      </div>

      {/* When in IDLE or PROCESSING: Show Uploader */}
      {(receiptScan.status === 'idle' ||
        receiptScan.status === 'uploading' ||
        receiptScan.status === 'processing') && (
        <ReceiptUploader />
      )}

      {/* When in REVIEW: Show 2-Column Split Interface */}
      {receiptScan.status === 'review' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Receipt Image & Structured Paper Preview */}
          <div className="lg:col-span-5 space-y-6">
            <ReceiptPreview
              previewUrl={receiptScan.previewUrl}
              extractedData={receiptScan.extractedData}
              confidence={receiptScan.confidence}
            />
          </div>

          {/* Right Column: AI Extraction Verification & Member Item Assignment */}
          <div className="lg:col-span-7 space-y-6">
            <ExtractionResult />
            <ItemSplitAssignment
              onFinalized={() => onNavigate('groups')}
            />
          </div>
        </div>
      )}

      {/* Error state */}
      {receiptScan.status === 'error' && (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-8 border border-rose-200 dark:border-rose-900/60 text-center max-w-lg mx-auto space-y-4">
          <div className="w-12 h-12 rounded-full bg-rose-50 dark:bg-rose-950/60 text-rose-600 mx-auto flex items-center justify-center font-bold text-lg">
            !
          </div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            AI Extraction Encountered an Issue
          </h3>
          <p className="text-xs text-rose-600 dark:text-rose-400">
            {receiptScan.error}
          </p>
          <Button
            variant="primary"
            size="md"
            icon={RotateCcw}
            onClick={resetReceiptScan}
          >
            Upload Another Receipt
          </Button>
        </div>
      )}
    </div>
  );
}
