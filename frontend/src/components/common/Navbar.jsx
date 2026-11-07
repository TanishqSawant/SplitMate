import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Sun,
  Moon,
  ChevronDown,
  UserCheck,
  Activity,
  Menu,
  X,
  CreditCard,
  ShieldCheck,
  RefreshCw
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';
import { apiClient } from '../../api/client';
import Badge from './Badge';

export default function Navbar({ onToggleSidebar, isSidebarOpen, onNavigate }) {
  const { currentUser, allUsers, switchUser } = useAuth();
  const { theme, toggleTheme, isDark } = useTheme();
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [backendStatus, setBackendStatus] = useState({ isOnline: null, baseURL: apiClient.baseURL });
  const [isPinging, setIsPinging] = useState(false);

  useEffect(() => {
    const unsubscribe = apiClient.subscribeStatus(setBackendStatus);
    apiClient.checkHealth();
    return () => unsubscribe();
  }, []);

  const handlePingBackend = async () => {
    setIsPinging(true);
    await apiClient.checkHealth();
    setTimeout(() => setIsPinging(false), 500);
  };

  return (
    <header className="sticky top-0 z-40 w-full bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-slate-200/80 dark:border-slate-800 transition-colors">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        
        {/* Left: Hamburger & Logo */}
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleSidebar}
            className="lg:hidden p-2 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
            aria-label="Toggle Navigation"
          >
            {isSidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>

          <div
            onClick={() => onNavigate('dashboard')}
            className="flex items-center gap-2.5 cursor-pointer group select-none"
          >
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-[#003087] via-[#0070BA] to-sky-400 flex items-center justify-center text-white shadow-md shadow-blue-500/20 group-hover:scale-105 transition-transform">
              <Sparkles className="w-5 h-5" />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="font-extrabold text-lg tracking-tight bg-gradient-to-r from-slate-900 via-blue-900 to-[#0070BA] dark:from-white dark:via-blue-200 dark:to-[#0070BA] bg-clip-text text-transparent">
                  SplitMate
                </span>
                <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-950/70 text-[#0070BA] dark:text-blue-300">
                  AI + PayPal
                </span>
              </div>
              <span className="text-[10px] text-slate-400 dark:text-slate-500 font-medium">
                Smart Expense Splitting
              </span>
            </div>
          </div>
        </div>

        {/* Center: Backend Health Status Pill */}
        <div className="hidden md:flex items-center gap-2">
          <div
            onClick={handlePingBackend}
            className="group flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium cursor-pointer transition-all border bg-slate-50 hover:bg-slate-100 dark:bg-slate-800/60 dark:hover:bg-slate-800 border-slate-200 dark:border-slate-700/60"
            title="Click to ping FastAPI backend server"
          >
            <span className="relative flex h-2 w-2">
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  backendStatus.isOnline === true ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              />
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  backendStatus.isOnline === true ? 'bg-emerald-500' : 'bg-amber-500'
                }`}
              />
            </span>
            <span className="text-slate-600 dark:text-slate-300">
              {backendStatus.isOnline === true
                ? 'FastAPI Live'
                : 'Demo Resilient Mode'}
            </span>
            <RefreshCw
              className={`w-3 h-3 text-slate-400 group-hover:text-slate-600 dark:group-hover:text-slate-200 ${
                isPinging ? 'animate-spin' : ''
              }`}
            />
          </div>

          <Badge variant="paypal" size="sm">
            <ShieldCheck className="w-3 h-3" />
            PayPal Sandbox
          </Badge>
        </div>

        {/* Right: Teammate Switcher, Theme Toggle, Profile */}
        <div className="flex items-center gap-2.5">
          {/* Theme Toggle */}
          <button
            onClick={toggleTheme}
            className="p-2 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title={`Switch to ${isDark ? 'light' : 'dark'} mode`}
            aria-label="Toggle dark mode"
          >
            {isDark ? <Sun className="w-5 h-5 text-amber-400" /> : <Moon className="w-5 h-5 text-slate-600" />}
          </button>

          {/* Hackathon Teammate Quick Switcher */}
          <div className="relative">
            <button
              onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
              className="flex items-center gap-2 p-1.5 pl-2 sm:pr-3 rounded-xl border border-slate-200 dark:border-slate-700/80 hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-all text-left"
              aria-label="Select Team Member Role"
            >
              <img
                src={currentUser?.avatar}
                alt={currentUser?.name}
                className="w-7 h-7 rounded-lg object-cover ring-2 ring-blue-500/20"
              />
              <div className="hidden sm:flex flex-col text-left">
                <span className="text-xs font-semibold text-slate-900 dark:text-white leading-tight">
                  {currentUser?.name}
                </span>
                <span className="text-[10px] text-blue-600 dark:text-blue-400 leading-tight truncate max-w-[120px]">
                  {currentUser?.role?.split(' ')[0]} Lead
                </span>
              </div>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400 hidden sm:block" />
            </button>

            {/* Dropdown Menu */}
            {isUserMenuOpen && (
              <>
                <div
                  className="fixed inset-0 z-30"
                  onClick={() => setIsUserMenuOpen(false)}
                />
                <div className="absolute right-0 mt-2 w-72 bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 py-2 z-40 animate-in fade-in zoom-in-95 duration-150">
                  <div className="px-4 py-2 border-b border-slate-100 dark:border-slate-800">
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                      Hackathon Team Persona
                    </p>
                    <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                      Switch roles to test different permissions & PayPal balances:
                    </p>
                  </div>

                  <div className="max-h-64 overflow-y-auto py-1">
                    {allUsers.map((user) => {
                      const isActive = user.id === currentUser?.id;
                      return (
                        <button
                          key={user.id}
                          onClick={() => {
                            switchUser(user.id);
                            setIsUserMenuOpen(false);
                          }}
                          className={`w-full flex items-center gap-3 px-4 py-2.5 text-left text-sm transition-colors ${
                            isActive
                              ? 'bg-blue-50/80 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 font-semibold'
                              : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/60'
                          }`}
                        >
                          <img
                            src={user.avatar}
                            alt={user.name}
                            className="w-8 h-8 rounded-lg object-cover ring-1 ring-slate-200 dark:ring-slate-700"
                          />
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-semibold truncate">{user.name}</p>
                            <p className="text-[11px] text-slate-400 dark:text-slate-500 truncate">{user.role}</p>
                          </div>
                          {isActive && <UserCheck className="w-4 h-4 text-blue-600" />}
                        </button>
                      );
                    })}
                  </div>

                  <div className="px-3 pt-2 mt-1 border-t border-slate-100 dark:border-slate-800">
                    <div className="text-[11px] text-slate-400 dark:text-slate-500 flex items-center gap-1.5 px-1 py-1">
                      <CreditCard className="w-3.5 h-3.5 text-[#0070BA]" />
                      <span>{currentUser?.paypalEmail}</span>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

      </div>
    </header>
  );
}

