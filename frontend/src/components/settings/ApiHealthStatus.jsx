import React, { useState, useEffect } from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Server
} from 'lucide-react';
import { apiClient } from '../../api/client';
import Button from '../common/Button';
import Badge from '../common/Badge';

export default function ApiHealthStatus() {
  const [status, setStatus] = useState({ isOnline: null, baseURL: apiClient.baseURL });
  const [isChecking, setIsChecking] = useState(false);
  const [lastPingTime, setLastPingTime] = useState(null);
  const [latency, setLatency] = useState(null);

  useEffect(() => {
    return apiClient.subscribeStatus(setStatus);
  }, []);

  const handlePing = async () => {
    setIsChecking(true);
    const start = performance.now();
    await apiClient.checkHealth();
    const end = performance.now();
    setLatency(Math.round(end - start));
    setLastPingTime(new Date().toLocaleTimeString());
    setIsChecking(false);
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-100 dark:border-slate-800">
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <Server className="w-5 h-5 text-blue-600" />
            Backend API Health & Team Contracts
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Real-time connectivity monitoring with Tanishq's FastAPI server
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          icon={RefreshCw}
          isLoading={isChecking}
          onClick={handlePing}
        >
          Ping FastAPI Server
        </Button>
      </div>

      {/* Connectivity Status Banner */}
      <div className={`p-4 rounded-xl border flex items-center justify-between ${
        status.isOnline === true
          ? 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200'
          : 'bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200'
      }`}>
        <div className="flex items-center gap-3">
          {status.isOnline === true ? (
            <CheckCircle2 className="w-6 h-6 text-emerald-600 dark:text-emerald-400 shrink-0" />
          ) : (
            <AlertTriangle className="w-6 h-6 text-amber-600 dark:text-amber-400 shrink-0" />
          )}
          <div>
            <p className="text-sm font-bold">
              {status.isOnline === true
                ? 'FastAPI Server Connected'
                : 'Demo Resilient Mode Active (Backend Offline)'}
            </p>
            <p className="text-xs opacity-90 mt-0.5">
              Target Base URL: <code className="font-mono">{status.baseURL}</code>
              {latency && ` • Ping: ${latency}ms`}
              {lastPingTime && ` • Checked at ${lastPingTime}`}
            </p>
          </div>
        </div>

        <Badge
          variant={status.isOnline === true ? 'success' : 'warning'}
          size="sm"
        >
          {status.isOnline === true ? 'Live 200 OK' : 'Local Fallback'}
        </Badge>
      </div>

      {/* Agreed Team API Contracts Table */}
      <div className="space-y-3">
        <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
          Agreed Hackathon API Endpoint Contracts
        </h4>

        <div className="rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden divide-y divide-slate-100 dark:divide-slate-800 text-xs">
          {/* Tanishq */}
          <div className="p-3 bg-slate-50/50 dark:bg-slate-800/30 flex items-center justify-between">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-blue-600 dark:text-blue-400">
                  GET /api/health
                </span>
                <span className="font-mono font-semibold text-slate-500">
                  GET /api/groups
                </span>
                <span className="font-mono font-semibold text-slate-500">
                  POST /api/expenses
                </span>
              </div>
              <p className="text-[11px] text-slate-500">
                FastAPI Backend, Database models, and balance computation
              </p>
            </div>
            <Badge variant="primary" size="sm">
              Tanishq
            </Badge>
          </div>

          {/* Pawan */}
          <div className="p-3 bg-slate-50/50 dark:bg-slate-800/30 flex items-center justify-between">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-purple-600 dark:text-purple-400">
                  POST /api/receipts/extract
                </span>
              </div>
              <p className="text-[11px] text-slate-500">
                Multipart image upload -&gt; Computer Vision AI OCR line items & tax
              </p>
            </div>
            <Badge variant="purple" size="sm">
              Pawan
            </Badge>
          </div>

          {/* Tanay */}
          <div className="p-3 bg-slate-50/50 dark:bg-slate-800/30 flex items-center justify-between">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="font-mono font-bold text-[#0070BA] dark:text-blue-400">
                  POST /api/payments/paypal/create-order
                </span>
                <span className="font-mono font-bold text-[#0070BA] dark:text-blue-400">
                  POST /api/payments/paypal/capture-order
                </span>
              </div>
              <p className="text-[11px] text-slate-500">
                PayPal Sandbox server SDK order initialization and capture
              </p>
            </div>
            <Badge variant="paypal" size="sm">
              Tanay
            </Badge>
          </div>
        </div>
      </div>
    </div>
  );
}

