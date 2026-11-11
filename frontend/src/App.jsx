import React, { useState } from 'react';
import { PayPalScriptProvider } from '@paypal/react-paypal-js';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ExpenseProvider, useExpenses } from './context/ExpenseContext';

import Navbar from './components/common/Navbar';
import Sidebar from './components/common/Sidebar';

import DashboardView from './views/DashboardView';
import ReceiptScanView from './views/ReceiptScanView';
import GroupsView from './views/GroupsView';
import PayPalView from './views/PayPalView';
import TransactionsView from './views/TransactionsView';
import AnalyticsView from './views/AnalyticsView';
import SettingsView from './views/SettingsView';
import AuthView from './views/AuthView';

import PayPalPaymentModal from './components/payments/PayPalPaymentModal';
import ExpenseDetailModal from './components/expenses/ExpenseDetailModal';
import CreateGroupModal from './components/expenses/CreateGroupModal';
import AddExpenseModal from './components/expenses/AddExpenseModal';

function MainApp() {
  const { isAuthenticated, currentUser } = useAuth();
  const [currentView, setCurrentView] = useState('dashboard');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isCreateGroupOpen, setIsCreateGroupOpen] = useState(false);
  const [isAddExpenseOpen, setIsAddExpenseOpen] = useState(false);
  const [selectedExpense, setSelectedExpense] = useState(null);

  const { loadSampleReceipt } = useExpenses();

  if (!isAuthenticated || !currentUser) {
    return <AuthView />;
  }

  const handleScanReceipt = () => {
    setCurrentView('receipt-scan');
  };

  const handleLoadSampleAndScan = (sampleId) => {
    loadSampleReceipt(sampleId);
    setCurrentView('receipt-scan');
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 flex flex-col font-sans selection:bg-blue-600 selection:text-white transition-colors duration-200">
      {/* Top Fixed Navbar */}
      <Navbar
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        isSidebarOpen={isSidebarOpen}
        onNavigate={(view) => setCurrentView(view)}
      />

      {/* Main Body Area: Sidebar + Content */}
      <div className="flex-1 flex max-w-7xl w-full mx-auto">
        <Sidebar
          currentView={currentView}
          onNavigate={(view) => setCurrentView(view)}
          isOpen={isSidebarOpen}
          onClose={() => setIsSidebarOpen(false)}
        />

        <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-full overflow-hidden">
          {currentView === 'dashboard' && (
            <DashboardView
              onNavigate={(view) => setCurrentView(view)}
              onScanReceipt={handleScanReceipt}
              onAddExpense={() => setIsAddExpenseOpen(true)}
              onCreateGroup={() => setIsCreateGroupOpen(true)}
              onLoadSampleReceipt={handleLoadSampleAndScan}
              onSelectExpense={(exp) => setSelectedExpense(exp)}
            />
          )}

          {currentView === 'receipt-scan' && (
            <ReceiptScanView
              onNavigate={(view) => setCurrentView(view)}
            />
          )}

          {currentView === 'groups' && (
            <GroupsView
              onScanReceipt={handleScanReceipt}
              onSelectExpense={(exp) => setSelectedExpense(exp)}
            />
          )}

          {currentView === 'paypal' && <PayPalView />}

          {currentView === 'transactions' && (
            <TransactionsView
              onSelectExpense={(exp) => setSelectedExpense(exp)}
            />
          )}

          {currentView === 'analytics' && <AnalyticsView />}

          {currentView === 'settings' && <SettingsView />}
        </main>
      </div>

      {/* Global Modals */}
      <PayPalPaymentModal />

      <ExpenseDetailModal
        expense={selectedExpense}
        isOpen={Boolean(selectedExpense)}
        onClose={() => setSelectedExpense(null)}
      />

      <CreateGroupModal
        isOpen={isCreateGroupOpen}
        onClose={() => setIsCreateGroupOpen(false)}
      />

      <AddExpenseModal
        isOpen={isAddExpenseOpen}
        onClose={() => setIsAddExpenseOpen(false)}
      />
    </div>
  );
}

export default function App() {
  const paypalOptions = {
    clientId: (typeof import.meta !== 'undefined' && import.meta.env?.VITE_PAYPAL_CLIENT_ID) || 'sb',
    currency: 'USD',
    intent: 'capture',
    components: 'buttons',
  };

  return (
    <ThemeProvider>
      <AuthProvider>
        <PayPalScriptProvider options={paypalOptions}>
          <ExpenseProvider>
            <MainApp />
          </ExpenseProvider>
        </PayPalScriptProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
