import React, { useState } from 'react';
import {
  ZoomIn,
  ZoomOut,
  Receipt,
  Sparkles
} from 'lucide-react';
import Badge from '../common/Badge';

export default function ReceiptPreview({ previewUrl, extractedData, confidence }) {
  const [isZoomed, setIsZoomed] = useState(false);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-5 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
          <Receipt className="w-4 h-4 text-[#0070BA]" />
          Receipt Image & Preview
        </h4>
        <div className="flex items-center gap-2">
          {confidence != null && (
            <Badge variant="purple" size="sm">
              <Sparkles className="w-3 h-3" />
              {Math.round(confidence * 100)}% Confidence
            </Badge>
          )}
          {extractedData?.extractionStatus === 'review_required' && (
            <Badge variant="warning" size="sm">
              Review Required
            </Badge>
          )}
          {extractedData?.extractionStatus === 'completed' && (
            <Badge variant="success" size="sm">
              Completed
            </Badge>
          )}
          <button
            onClick={() => setIsZoomed(!isZoomed)}
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
            title={isZoomed ? 'Zoom out' : 'Zoom in'}
          >
            {isZoomed ? <ZoomOut className="w-4 h-4" /> : <ZoomIn className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Image Preview Container */}
      <div
        className={`relative overflow-hidden rounded-xl bg-slate-950 flex items-center justify-center transition-all duration-300 ${
          isZoomed ? 'h-96' : 'h-64'
        }`}
      >
        {previewUrl ? (
          <img
            src={previewUrl}
            alt="Scanned Receipt"
            className={`w-full h-full object-contain transition-transform duration-200 ${
              isZoomed ? 'scale-125 cursor-zoom-out' : 'cursor-zoom-in'
            }`}
            onClick={() => setIsZoomed(!isZoomed)}
          />
        ) : (
          <div className="text-center p-6 text-slate-400">
            <Receipt className="w-12 h-12 mx-auto mb-2 opacity-50" />
            <p className="text-xs">No image preview available</p>
          </div>
        )}
      </div>

      {/* Structured Receipt Summary Card */}
      {extractedData && (
        <div className="receipt-paper p-4 rounded-xl border border-dashed border-slate-300 dark:border-slate-700 font-mono text-xs space-y-2 text-slate-700 dark:text-slate-300">
          <div className="text-center pb-2 border-b border-dashed border-slate-300 dark:border-slate-700">
            <p className="font-bold text-sm tracking-wide text-slate-900 dark:text-white uppercase font-sans">
              {extractedData.merchant || <span className="text-amber-500 italic lowercase font-normal">Merchant not detected</span>}
            </p>
            <p className="text-[11px] text-slate-400 font-sans mt-0.5">
              {extractedData.date || 'No date'} • {extractedData.currency ? `${extractedData.currency} currency` : <span className="text-amber-500 italic">Currency unknown</span>}
            </p>
          </div>

          <div className="flex justify-between pt-1">
            <span>Subtotal</span>
            <span>
              {extractedData.subtotal != null
                ? `${extractedData.currency ? extractedData.currency + ' ' : ''}${Number(extractedData.subtotal).toFixed(2)}`
                : <span className="text-slate-400 italic">Not detected</span>}
            </span>
          </div>

          <div className="flex justify-between">
            <span>Sales Tax</span>
            <span>
              {extractedData.tax != null
                ? `${extractedData.currency ? extractedData.currency + ' ' : ''}${Number(extractedData.tax).toFixed(2)}`
                : <span className="text-slate-400 italic">Not detected</span>}
            </span>
          </div>

          <div className="flex justify-between">
            <span>Gratuity / Tip</span>
            <span>
              {extractedData.tip != null
                ? `${extractedData.currency ? extractedData.currency + ' ' : ''}${Number(extractedData.tip).toFixed(2)}`
                : <span className="text-slate-400 italic">None</span>}
            </span>
          </div>

          <div className="flex justify-between pt-2 border-t border-dashed border-slate-300 dark:border-slate-700 font-bold text-sm text-slate-900 dark:text-white">
            <span>TOTAL AMOUNT</span>
            <span className={extractedData.total != null ? "text-blue-600 dark:text-blue-400" : "text-amber-500"}>
              {extractedData.total != null
                ? `${extractedData.currency ? extractedData.currency + ' ' : ''}${Number(extractedData.total).toFixed(2)}`
                : <span className="text-amber-500 text-xs italic font-normal">Missing total (Review required)</span>}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
