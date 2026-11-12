import React, { useState } from 'react';
import { Sparkles, LogIn, UserPlus, AlertCircle, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Button from '../components/common/Button';

export default function AuthView() {
  const { login, register, isLoading } = useAuth();
  const [mode, setMode] = useState('login'); // 'login' | 'register'
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
  });
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (mode === 'login') {
      const result = await login(formData.email, formData.password);
      if (!result.success) {
        setError(result.error || 'Login failed');
      }
    } else {
      if (!formData.name.trim()) {
        setError('Name is required');
        return;
      }
      if (formData.password.length < 8) {
        setError('Password must be at least 8 characters');
        return;
      }
      const result = await register(formData);
      if (!result.success) {
        setError(result.error || 'Registration failed');
      }
    }
  };

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-100 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2.5 mb-3">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-[#003087] via-[#0070BA] to-sky-400 flex items-center justify-center text-white shadow-lg shadow-blue-500/30">
              <Sparkles className="w-6 h-6" />
            </div>
            <div className="flex flex-col items-start">
              <span className="font-extrabold text-2xl tracking-tight bg-gradient-to-r from-slate-900 via-blue-900 to-[#0070BA] dark:from-white dark:via-blue-200 dark:to-[#0070BA] bg-clip-text text-transparent">
                SplitMate
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">
                AI + PayPal Expense Splitting
              </span>
            </div>
          </div>
        </div>

        {/* Auth Card */}
        <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 p-8">
          {/* Mode Toggle */}
          <div className="flex gap-2 mb-6 p-1 bg-slate-100 dark:bg-slate-800 rounded-xl">
            <button
              onClick={() => setMode('login')}
              className={`flex-1 py-2 px-4 rounded-lg text-sm font-semibold transition-all ${
                mode === 'login'
                  ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              <LogIn className="w-4 h-4 inline-block mr-1.5" />
              Sign In
            </button>
            <button
              onClick={() => setMode('register')}
              className={`flex-1 py-2 px-4 rounded-lg text-sm font-semibold transition-all ${
                mode === 'register'
                  ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              <UserPlus className="w-4 h-4 inline-block mr-1.5" />
              Sign Up
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === 'register' && (
              <div>
                <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                  Name
                </label>
                <input
                  type="text"
                  name="name"
                  value={formData.name}
                  onChange={handleChange}
                  placeholder="John Doe"
                  required
                  className="w-full px-4 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                Email
              </label>
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                placeholder="you@example.com"
                required
                className="w-full px-4 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
              />
            </div>

            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                Password
              </label>
              <input
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                placeholder={mode === 'register' ? 'At least 8 characters' : '••••••••'}
                required
                minLength={mode === 'register' ? 8 : undefined}
                className="w-full px-4 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder-slate-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
              />
            </div>

            {error && (
              <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300 text-sm flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full"
              disabled={isLoading}
              icon={isLoading ? Loader2 : mode === 'login' ? LogIn : UserPlus}
            >
              {isLoading ? 'Processing...' : mode === 'login' ? 'Sign In' : 'Create Account'}
            </Button>
          </form>

          {mode === 'login' && (
            <p className="text-xs text-center text-slate-500 dark:text-slate-400 mt-4">
              Sign in with your registered SplitMate account
            </p>
          )}
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-slate-500 dark:text-slate-400 mt-6">
          PayPal Hackathon 2026 - SplitMate Team
        </p>
      </div>
    </div>
  );
}
