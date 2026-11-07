import React from 'react';
import ProfileForm from '../components/settings/ProfileForm';
import ApiHealthStatus from '../components/settings/ApiHealthStatus';
import Badge from '../components/common/Badge';
import { Settings, ShieldCheck, Key, Code } from 'lucide-react';

export default function SettingsView() {
  return (
    <div className="space-y-6 animate-in fade-in duration-150">
      <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-slate-800">
        <div>
          <h2 className="text-xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Settings & Backend Integrations
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Manage your profile, connected PayPal sandbox account, and team API endpoints
          </p>
        </div>

        <Badge variant="paypal" size="sm">
          <ShieldCheck className="w-3.5 h-3.5" />
          Environment: Sandbox
        </Badge>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ProfileForm />
        <ApiHealthStatus />
      </div>

      {/* Developer Integration Specs & Notes for Hackathon Teammates */}
      <div className="bg-slate-50 dark:bg-slate-900/60 rounded-2xl p-6 border border-slate-200 dark:border-slate-800 space-y-3">
        <div className="flex items-center gap-2">
          <Code className="w-4 h-4 text-[#0070BA]" />
          <h4 className="text-sm font-bold text-slate-900 dark:text-white">
            Developer Handoff Notes for Teammates
          </h4>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-600 dark:text-slate-400">
          <div className="p-3 rounded-xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
            <p className="font-bold text-blue-600 dark:text-blue-400 mb-1">Tanishq (FastAPI):</p>
            <p className="leading-relaxed">
              Base URL configured as <code>http://localhost:8000/api</code> in <code>.env</code>. Frontend automatically falls back to offline resilient mocks whenever server is offline!
            </p>
          </div>

          <div className="p-3 rounded-xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
            <p className="font-bold text-purple-600 dark:text-purple-400 mb-1">Pawan (AI OCR):</p>
            <p className="leading-relaxed">
              Endpoint is <code>POST /api/receipts/extract</code> expecting <code>multipart/form-data</code> with field name <code>receipt</code>.
            </p>
          </div>

          <div className="p-3 rounded-xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
            <p className="font-bold text-[#0070BA] dark:text-blue-400 mb-1">Tanay (PayPal):</p>
            <p className="leading-relaxed">
              Order creation at <code>/payments/paypal/create-order</code> and capture at <code>/payments/paypal/capture-order</code>.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

