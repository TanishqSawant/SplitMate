import React from 'react';
import {
  Sparkles,
  RotateCcw,
  UploadCloud,
  Clock,
  AlertTriangle,
  ServerCrash,
  WifiOff,
} from 'lucide-react';
import { useExpenses } from '../context/ExpenseContext';
import ReceiptUploader from '../components/receipt/ReceiptUploader';
import ReceiptPreview from '../components/receipt/ReceiptPreview';
import ExtractionResult from '../components/receipt/ExtractionResult';
import ItemSplitAssignment from '../components/receipt/ItemSplitAssignment';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';

// Categorise the error message to pick the right icon and contextual advice
function classifyError(errorMsg) {
  const msg = (errorMsg || '').toLowerCase();
  if (
    msg.includes('authentication required') ||
    msg.includes('bearer token') ||
    msg.includes('unauthorized') ||
    msg.includes('session token')
  ) {
    return {
      icon: AlertTriangle,
      title: 'Authentication Required',
      advice:
        'A valid session token is required to upload receipts. Please sign in to your SplitMate account.',
      color: 'amber',
    };
  }
  if (
    msg.includes('unable to connect') ||
    msg.includes('unreachable') ||
    msg.includes('failed to fetch') ||
    msg.includes('econnrefused')
  ) {
    return {
      icon: WifiOff,
      title: 'Backend Service Offline',
      advice:
        'The SplitMate backend server is not reachable at http://localhost:8000. Ask Tanishq to start the FastAPI server, then retry.',
      color: 'amber',
    };
  }
  if (
    msg.includes('not appear to contain') ||
    msg.includes('not a receipt') ||
    msg.includes('invalid image')
  ) {
    return {
      icon: AlertTriangle,
      title: 'Not a Valid Receipt',
      advice:
        'The uploaded image does not appear to be a receipt. Please upload a clear photo of a restaurant bill, store receipt, or invoice.',
      color: 'orange',
    };
  }
  if (msg.includes('blur') || msg.includes('quality')) {
    return {
      icon: AlertTriangle,
      title: 'Image Too Blurry',
      advice:
        'The receipt image is unclear. Please take a fresh, well-lit photo and try again.',
      color: 'orange',
    };
  }
  if (msg.includes('too large') || msg.includes('413')) {
    return {
      icon: AlertTriangle,
      title: 'File Too Large',
      advice:
        'The file exceeds the 10 MB limit. Compress or resize the image and try again.',
      color: 'orange',
    };
  }
  return {
    icon: ServerCrash,
    title: 'Extraction Failed',
    advice:
      'An unexpected error occurred during extraction. Please try again, or contact Pawan if the problem persists.',
    color: 'rose',
  };
}

export default function ReceiptScanView({ onNavigate }) {
  const { receiptScan, resetReceiptScan, processReceiptFile } = useExpenses();
  const {
    icon: ErrorIcon,
    title: errorTitle,
    advice: errorAdvice,
    color: errorColor,
  } = classifyError(receiptScan.error);

  const colorMap = {
    amber: {
      card: 'border-amber-200 dark:border-amber-900/60',
      icon: 'bg-amber-50 dark:bg-amber-950/60 text-amber-600',
      title: 'text-slate-900 dark:text-white',
      msg: 'text-amber-700 dark:text-amber-400',
      advice: 'text-slate-500 dark:text-slate-400',
    },
    orange: {
      card: 'border-orange-200 dark:border-orange-900/60',
      icon: 'bg-orange-50 dark:bg-orange-950/60 text-orange-600',
      title: 'text-slate-900 dark:text-white',
      msg: 'text-orange-700 dark:text-orange-400',
      advice: 'text-slate-500 dark:text-slate-400',
    },
    rose: {
      card: 'border-rose-200 dark:border-rose-900/60',
      icon: 'bg-rose-50 dark:bg-rose-950/60 text-rose-600',
      title: 'text-slate-900 dark:text-white',
      msg: 'text-rose-700 dark:text-rose-400',
      advice: 'text-slate-500 dark:text-slate-400',
    },
  };
  const c = colorMap[errorColor] || colorMap.rose;

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
              SplitMate Vision AI
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

      {/* IDLE / UPLOADING / PROCESSING: Show Uploader */}
      {(receiptScan.status === 'idle' ||
        receiptScan.status === 'uploading' ||
        receiptScan.status === 'processing') && (
        <ReceiptUploader />
      )}

      {/* PENDING: AI service is working, polling timed out waiting for backend callback */}
      {receiptScan.status === 'pending' && (
        <div className="bg-white dark:bg-slate-900 rounded-2xl p-8 border border-blue-200 dark:border-blue-900/60 text-center max-w-lg mx-auto space-y-4">
          <div className="w-14 h-14 rounded-full bg-blue-50 dark:bg-blue-950/60 text-blue-600 mx-auto flex items-center justify-center">
            <Clock className="w-7 h-7 animate-pulse" />
          </div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            AI Extraction In Progress
          </h3>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Your receipt was uploaded successfully. SplitMate's AI vision service is processing it — this usually takes under 30 seconds.
          </p>
          <p className="text-xs text-blue-600 dark:text-blue-400 font-mono">
            Receipt ID: {receiptScan.receiptId}
          </p>
          <div className="flex items-center justify-center gap-3 pt-2">
            <Button
              variant="primary"
              size="md"
              icon={RotateCcw}
              onClick={() => receiptScan.file && processReceiptFile(receiptScan.file)}
            >
              Check Again
            </Button>
            <Button
              variant="ghost"
              size="md"
              icon={UploadCloud}
              onClick={resetReceiptScan}
            >
              Upload Different Receipt
            </Button>
          </div>
        </div>
      )}

      {/* REVIEW: Show 2-Column Split Interface */}
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

      {/* ERROR: Professional error UI with contextual advice + retry options */}
      {receiptScan.status === 'error' && (
        <div className={`bg-white dark:bg-slate-900 rounded-2xl p-8 border ${c.card} max-w-lg mx-auto space-y-5`}>
          {/* Icon */}
          <div className={`w-14 h-14 rounded-full ${c.icon} mx-auto flex items-center justify-center`}>
            <ErrorIcon className="w-7 h-7" />
          </div>

          {/* Title */}
          <div className="text-center space-y-2">
            <h3 className={`text-base font-bold ${c.title}`}>
              {errorTitle}
            </h3>
            <p className={`text-sm font-medium ${c.msg}`}>
              {receiptScan.error}
            </p>
            <p className={`text-xs leading-relaxed ${c.advice}`}>
              {errorAdvice}
            </p>
          </div>

          {/* Action buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
            {/* Retry re-runs the same file through processReceiptFile */}
            {receiptScan.file && (
              <Button
                variant="primary"
                size="md"
                icon={RotateCcw}
                onClick={() => processReceiptFile(receiptScan.file)}
              >
                Retry Extraction
              </Button>
            )}
            <Button
              variant={receiptScan.file ? 'outline' : 'primary'}
              size="md"
              icon={UploadCloud}
              onClick={resetReceiptScan}
            >
              Upload Different Receipt
            </Button>
          </div>

          {/* Backend status hint when offline */}
          {(receiptScan.error || '').toLowerCase().includes('connect') && (
            <div className="bg-slate-50 dark:bg-slate-800/60 rounded-xl p-3 text-xs text-slate-500 dark:text-slate-400 font-mono text-center space-y-1">
              <p className="font-semibold text-slate-700 dark:text-slate-300">Backend Startup Commands</p>
              <p>cd SplitMate/backend</p>
              <p>uvicorn app.main:app --reload --host 0.0.0.0 --port 8000</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
