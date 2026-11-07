import React, { useState } from 'react';
import { User, Mail, CreditCard, Save, Check } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import Button from '../common/Button';

export default function ProfileForm() {
  const { currentUser, updateProfile } = useAuth();

  const [name, setName] = useState(currentUser?.name || '');
  const [email, setEmail] = useState(currentUser?.email || '');
  const [paypalEmail, setPaypalEmail] = useState(currentUser?.paypalEmail || '');
  const [currency, setCurrency] = useState('USD');
  const [isSaved, setIsSaved] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    updateProfile({
      name,
      email,
      paypalEmail,
    });
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2500);
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200/80 dark:border-slate-800 shadow-xs space-y-6">
      <div className="flex items-center gap-4 pb-4 border-b border-slate-100 dark:border-slate-800">
        <img
          src={currentUser?.avatar}
          alt={currentUser?.name}
          className="w-16 h-16 rounded-2xl object-cover ring-4 ring-blue-500/10"
        />
        <div>
          <h3 className="text-base font-bold text-slate-900 dark:text-white">
            {currentUser?.name}
          </h3>
          <p className="text-xs text-blue-600 dark:text-blue-400 font-medium">
            {currentUser?.role}
          </p>
          <p className="text-xs text-slate-400 mt-0.5 font-mono">
            {currentUser?.email}
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Full Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3.5 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Account Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3.5 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              PayPal Sandbox Receiver Email
            </label>
            <div className="relative">
              <span className="absolute left-3 top-2.5 text-slate-400">
                <CreditCard className="w-4 h-4 text-[#0070BA]" />
              </span>
              <input
                type="email"
                value={paypalEmail}
                onChange={(e) => setPaypalEmail(e.target.value)}
                placeholder="facilitator@sandbox.paypal.com"
                className="w-full pl-9 pr-3.5 py-2 text-sm font-mono rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Preferred Currency
            </label>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="w-full px-3.5 py-2 text-sm rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:ring-2 focus:ring-blue-500"
            >
              <option value="USD">USD ($) - United States Dollar</option>
              <option value="EUR">EUR (€) - Euro</option>
              <option value="GBP">GBP (£) - British Pound</option>
              <option value="INR">INR (₹) - Indian Rupee</option>
            </select>
          </div>
        </div>

        <div className="pt-2 flex items-center justify-between">
          {isSaved ? (
            <span className="text-xs text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1.5">
              <Check className="w-4 h-4" />
              Profile updated successfully!
            </span>
          ) : (
            <span className="text-xs text-slate-400">
              Changes saved to local session
            </span>
          )}

          <Button variant="primary" size="md" icon={Save} type="submit">
            Save Profile
          </Button>
        </div>
      </form>
    </div>
  );
}

