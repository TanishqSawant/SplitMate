import React, { useState } from 'react';
import {
  ZoomIn,
  ZoomOut,
  Receipt,
  Sparkles,
  Maximize2,
  X,
  CheckCircle2,
  AlertTriangle
} from 'lucide-react';
import Badge from '../common/Badge';

export default function ReceiptPreview({ previewUrl, extractedData, confidence }) {
  const [zoomLevel, setZoomLevel] = useState(1); // 1 = 100%, 1.5 = 150%, 2 = 200%
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleZoomToggle = () => {
    setZoomLevel((prev) => (prev === 1 ? 1.5 : prev === 1.5 ? 2 : 1));
  };

  // Math check
  const subtotal = extractedData?.subtotal ?? 0;
  const tax = extractedData?.tax ?? 0;
  const tip = extractedData?.tip ?? 0;
  const grandTotal = extractedData?.total ?? 0;
  const isMathValid = Math.abs(grandTotal - (subtotal + tax + tip)) < 0.05;

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
          <Receipt className="w-4 h-4 text-[#0070BA]" />
          Receipt Image & Preview
        </h4>
        <div className="flex items-center gap-1.5">
          {confidence != null ? (
            <Badge variant="purple" size="sm">
              <Sparkles className="w-3 h-3" />
              {Math.round(confidence * 100)}% Confidence
            </Badge>
          ) : (
            <Badge variant="default" size="sm">
              Confidence unavailable
            </Badge>
          )}

          <button
            onClick={handleZoomToggle}
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer"
            title={`Zoom (${zoomLevel}x)`}
            aria-label="Toggle Zoom"
          >
            {zoomLevel > 1 ? <ZoomOut className="w-4 h-4" /> : <ZoomIn className="w-4 h-4" />}
          </button>

          {previewUrl && (
            <button
              onClick={() => setIsModalOpen(true)}
              className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer"
              title="Full screen view"
              aria-label="Full screen view"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Image Preview Container */}
      <div
        className="relative overflow-auto rounded-xl bg-slate-950 flex items-center justify-center transition-all duration-300 min-h-[16rem] max-h-[22rem] p-2 border border-slate-800"
      >
        {previewUrl ? (
          <img
            src={previewUrl}
            alt="Scanned Receipt"
            style={{ transform: `scale(${zoomLevel})`, transformOrigin: 'top center' }}
            className="max-w-full max-h-full object-contain transition-transform duration-200 cursor-zoom-in"
            onClick={handleZoomToggle}
          />
        ) : (
          <div className="text-center p-6 text-slate-400">
            <Receipt className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <p className="text-xs">No image preview available</p>
          </div>
        )}

        {zoomLevel > 1 && (
          <span className="absolute bottom-2 right-2 bg-slate-900/90 text-white font-mono text-[10px] px-2 py-0.5 rounded-md border border-slate-700">
            {zoomLevel}x Zoom
          </span>
        )}
      </div>

      {/* Structured Receipt Summary Card */}
      {extractedData && (
        <div className="p-4 rounded-xl border border-dashed border-slate-300 dark:border-slate-700 font-mono text-xs space-y-2 text-slate-700 dark:text-slate-300 bg-slate-50/60 dark:bg-slate-800/30">
          <div className="text-center pb-2 border-b border-dashed border-slate-300 dark:border-slate-700">
            <p className="font-bold text-sm tracking-wide text-slate-900 dark:text-white uppercase font-sans">
              {extractedData.merchant || <span className="italic text-slate-400">Unspecified Merchant</span>}
            </p>
            <p className="text-[11px] text-slate-400 font-sans mt-0.5">
              {extractedData.date || 'Date not detected'} • {extractedData.category || 'General Dining'}
            </p>
          </div>

          <div className="flex justify-between pt-1">
            <span>Subtotal</span>
            <span>
              {extractedData.subtotal != null ? `$${extractedData.subtotal.toFixed(2)}` : '—'}
            </span>
          </div>

          <div className="flex justify-between">
            <span>Sales Tax</span>
            <span>
              {extractedData.tax != null ? (
                `$${extractedData.tax.toFixed(2)}`
              ) : (
                <span className="italic text-slate-400">Not detected ($0.00)</span>
              )}
            </span>
          </div>

          <div className="flex justify-between">
            <span>Gratuity / Tip</span>
            <span>
              {extractedData.tip != null ? (
                `$${extractedData.tip.toFixed(2)}`
              ) : (
                <span className="italic text-slate-400">$0.00</span>
              )}
            </span>
          </div>

          <div className="flex justify-between pt-2 border-t border-dashed border-slate-300 dark:border-slate-700 font-bold text-sm text-slate-900 dark:text-white">
            <span>TOTAL AMOUNT</span>
            <span className="text-blue-600 dark:text-blue-400">
              ${(extractedData.total || 0).toFixed(2)} {extractedData.currency || 'USD'}
            </span>
          </div>

          {/* Math Consistency Pill */}
          <div className="pt-2 border-t border-slate-200 dark:border-slate-700/60 flex items-center justify-between text-[10px]">
            <span className="font-sans text-slate-400">Reconciliation:</span>
            {isMathValid ? (
              <span className="text-emerald-600 dark:text-emerald-400 font-bold flex items-center gap-1 font-sans">
                <CheckCircle2 className="w-3 h-3" />
                Math Reconciled
              </span>
            ) : (
              <span className="text-amber-500 font-bold flex items-center gap-1 font-sans">
                <AlertTriangle className="w-3 h-3" />
                Discrepancy Flagged
              </span>
            )}
          </div>
        </div>
      )}

      {/* Fullscreen Inspection Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="relative max-w-4xl w-full max-h-[90vh] bg-slate-900 rounded-2xl overflow-hidden flex flex-col border border-slate-800 shadow-2xl">
            <div className="p-4 flex items-center justify-between border-b border-slate-800 text-white">
              <span className="font-bold text-sm">Receipt Detailed Inspector</span>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4 flex items-center justify-center">
              <img
                src={previewUrl}
                alt="Receipt Inspection"
                className="max-w-full max-h-[75vh] object-contain"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
