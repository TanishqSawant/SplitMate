import React from 'react';
import {
  LayoutDashboard,
  ScanLine,
  Users,
  CreditCard,
  Receipt,
  PieChart,
  Settings,
  Shield
} from 'lucide-react';
import Badge from './Badge';

export default function Sidebar({ currentView, onNavigate, isOpen, onClose }) {
  const navigationItems = [
    {
      id: 'dashboard',
      label: 'Dashboard',
      icon: LayoutDashboard,
      badge: null,
    },
    {
      id: 'receipt-scan',
      label: 'AI Receipt Scanner',
      icon: ScanLine,
      badge: 'Smart OCR',
      badgeVariant: 'purple',
    },
    {
      id: 'groups',
      label: 'Groups & Expenses',
      icon: Users,
      badge: null,
    },
    {
      id: 'paypal',
      label: 'PayPal Settle Up',
      icon: CreditCard,
      badge: 'Sandbox',
      badgeVariant: 'paypal',
    },
    {
      id: 'transactions',
      label: 'Transaction History',
      icon: Receipt,
      badge: null,
    },
    {
      id: 'analytics',
      label: 'Analytics & Debt Graph',
      icon: PieChart,
      badge: null,
    },
    {
      id: 'settings',
      label: 'Account & Settings',
      icon: Settings,
      badge: null,
    },
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-30 bg-slate-900/50 backdrop-blur-sm lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar container */}
      <aside
        className={`fixed lg:sticky top-16 z-30 h-[calc(100vh-4rem)] w-64 bg-white dark:bg-slate-900 border-r border-slate-200/80 dark:border-slate-800 flex flex-col justify-between p-4 transition-transform duration-200 ease-in-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="space-y-6">
          {/* Main Navigation links */}
          <nav className="space-y-1">
            <p className="px-3 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-2">
              Menu
            </p>
            {navigationItems.map((item) => {
              const Icon = item.icon;
              const isActive = currentView === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    onNavigate(item.id);
                    if (onClose) onClose();
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium transition-all group ${
                    isActive
                      ? 'bg-blue-50 dark:bg-blue-950/50 text-[#0070BA] dark:text-blue-400 shadow-xs'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100/70 dark:hover:bg-slate-800/50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <Icon
                      className={`w-5 h-5 transition-colors ${
                        isActive
                          ? 'text-[#0070BA] dark:text-blue-400'
                          : 'text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-300'
                      }`}
                    />
                    <span>{item.label}</span>
                  </div>

                  {item.badge && (
                    <Badge variant={item.badgeVariant || 'default'} size="sm">
                      {item.badge}
                    </Badge>
                  )}
                </button>
              );
            })}
          </nav>

          {/* SplitMate Security & Brand Card */}
          <div className="mx-1 p-3.5 rounded-2xl bg-gradient-to-br from-blue-50 to-indigo-50/50 dark:from-slate-800/80 dark:to-blue-950/30 border border-blue-100 dark:border-blue-900/50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-[#0070BA] dark:text-blue-400">
                SplitMate Intelligent
              </span>
              <Shield className="w-3.5 h-3.5 text-[#0070BA] dark:text-blue-400" />
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed font-normal">
              AI-powered bill scanning and instant peer-to-peer PayPal settlements.
            </p>
            <div className="mt-3 pt-2.5 border-t border-blue-200/50 dark:border-blue-800/40 flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
              <span>Sandbox Verified</span>
              <span className="font-semibold text-emerald-600 dark:text-emerald-400">Bank-Grade 256-Bit</span>
            </div>
          </div>
        </div>

        {/* Bottom Footer Info */}
        <div className="pt-4 border-t border-slate-200/80 dark:border-slate-800">
          <div className="flex items-center justify-between px-2 text-xs text-slate-400 dark:text-slate-500">
            <span>SplitMate v1.0</span>
            <span className="font-mono text-[10px]">React 19 + Vite</span>
          </div>
        </div>
      </aside>
    </>
  );
}

