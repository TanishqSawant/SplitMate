import React, { useState, useRef } from 'react';
import {
  UploadCloud,
  FileImage,
  Sparkles,
  CheckCircle,
  AlertCircle,
  ArrowRight,
  Camera,
  Layers
} from 'lucide-react';
import { useExpenses } from '../../context/ExpenseContext';
import { MOCK_SAMPLE_RECEIPTS } from '../../api/mockData';
import Button from '../common/Button';
import Badge from '../common/Badge';

export default function ReceiptUploader() {
  const { receiptScan, processReceiptFile, loadSampleReceipt } = useExpenses();
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type.startsWith('image/')) {
      processReceiptFile(files[0]);
    }
  };

  const handleFileChange = (e) => {
    const files = e.target.files;
    if (files.length > 0) {
      processReceiptFile(files[0]);
    }
  };

  return (
    <div className="space-y-6">
      {/* Upload Dropzone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`relative border-2 border-dashed rounded-3xl p-8 sm:p-12 text-center transition-all cursor-pointer ${
          isDragging
            ? 'border-blue-500 bg-blue-50/50 dark:bg-blue-950/30 scale-[1.01]'
            : 'border-slate-300 dark:border-slate-700 hover:border-blue-400 dark:hover:border-blue-500 bg-white dark:bg-slate-900/60'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png, image/jpeg, image/webp"
          className="hidden"
          onChange={handleFileChange}
        />

        <div className="flex flex-col items-center justify-center max-w-md mx-auto">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-500 text-white flex items-center justify-center shadow-lg shadow-blue-500/30 mb-4 transform group-hover:scale-105 transition-transform">
            <UploadCloud className="w-8 h-8" />
          </div>

          <h3 className="text-lg font-bold text-slate-900 dark:text-white">
            Upload or drop your receipt image
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 mb-4 leading-relaxed">
            Supports JPG, PNG, and WebP up to 15MB. Pawan's vision AI model will instantly parse line items, tax, and totals.
          </p>

          <div className="flex items-center gap-3">
            <Button
              variant="primary"
              size="md"
              icon={Camera}
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
            >
              Choose Receipt File
            </Button>
          </div>
        </div>

        {/* Upload & AI extraction Progress Bar */}
        {(receiptScan.status === 'uploading' || receiptScan.status === 'processing') && (
          <div className="absolute inset-0 bg-white/95 dark:bg-slate-900/95 rounded-3xl flex flex-col items-center justify-center p-6 backdrop-blur-sm z-20">
            <div className="w-full max-w-md space-y-4">
              <div className="flex items-center justify-between text-sm">
                <span className="font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-purple-600 animate-spin" />
                  {receiptScan.status === 'uploading'
                    ? 'Uploading receipt image...'
                    : "Pawan's AI Vision OCR analyzing line items..."}
                </span>
                <span className="font-mono text-xs text-blue-600 dark:text-blue-400 font-bold">
                  {receiptScan.progress}%
                </span>
              </div>

              <div className="w-full h-2.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 rounded-full transition-all duration-300"
                  style={{ width: `${receiptScan.progress}%` }}
                />
              </div>

              <p className="text-xs text-slate-400 text-center">
                Extracting merchant details, item names, individual prices, tax, and tip...
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Quick Demo Receipts Selection (Crucial for Hackathon presentation) */}
      <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-600" />
            <h4 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
              One-Click Hackathon Demo Samples
            </h4>
          </div>
          <Badge variant="purple" size="sm">
            AI Test Data
          </Badge>
        </div>

        <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
          Click any pre-scanned receipt below to test line-item splitting, tax pro-ration, and PayPal sandbox payments:
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {MOCK_SAMPLE_RECEIPTS.map((sample) => (
            <div
              key={sample.id}
              onClick={() => loadSampleReceipt(sample.id)}
              className="group border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5 hover:border-blue-500 dark:hover:border-blue-500 hover:shadow-md transition-all cursor-pointer bg-slate-50/50 dark:bg-slate-800/40 flex flex-col justify-between"
            >
              <div>
                <div className="h-28 rounded-xl overflow-hidden mb-3 relative">
                  <img
                    src={sample.image}
                    alt={sample.merchant}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                  />
                  <span className="absolute top-2 right-2 bg-slate-900/80 backdrop-blur-xs text-white text-[10px] font-mono font-bold px-2 py-0.5 rounded-md">
                    {Math.round(sample.confidence * 100)}% AI Match
                  </span>
                </div>

                <p className="text-xs font-bold text-slate-900 dark:text-white truncate">
                  {sample.merchant}
                </p>
                <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">
                  {sample.items.length} extracted items • {sample.category}
                </p>
              </div>

              <div className="mt-3 pt-2.5 border-t border-slate-200 dark:border-slate-700/60 flex items-center justify-between">
                <span className="text-sm font-extrabold text-blue-600 dark:text-blue-400">
                  ${sample.total.toFixed(2)}
                </span>
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 group-hover:text-blue-600 dark:group-hover:text-blue-400 flex items-center gap-1">
                  Load
                  <ArrowRight className="w-3.5 h-3.5" />
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

