
import React from 'react';
import ProfileForm from '../components/settings/ProfileForm';
import AccountOverview from '../components/settings/AccountOverview';
import Badge from '../components/common/Badge';
import { ShieldCheck, Lock, CheckCircle2 } from 'lucide-react';

export default function SettingsView() {
  return (
    <div className="space-y-6 animate-in fade-in duration-150">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-slate-100 dark:border-slate-800">
        <div>
          <h2 className="text-xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Account & Settings
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Manage your personal profile, connected PayPal account, and financial activity
          </p>
        </div>

        <Badge variant="paypal" size="sm">
          <ShieldCheck className="w-3.5 h-3.5" />
          PayPal Sandbox Verified
        </Badge>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ProfileForm />
        <AccountOverview />
      </div>

      {/* Security & Data Protection Banner */}
      <div className="p-4 rounded-2xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-blue-50 dark:bg-blue-950/70 text-[#0070BA] dark:text-blue-400">
            <Lock className="w-4 h-4" />
          </div>

          <div>
            <p className="font-semibold text-slate-900 dark:text-white">
              Security & Data Protection
            </p>
            <p className="text-[11px] mt-0.5">
              SplitMate does not store banking passwords or secret API keys in browser storage.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 font-semibold text-xs">
          <CheckCircle2 className="w-4 h-4" />
          <span>PayPal Sandbox Compliant</span>
        </div>
      </div>
    </div>
  );
}
