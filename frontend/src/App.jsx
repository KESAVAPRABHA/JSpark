import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import LoginPage       from './pages/LoginPage';
import DashboardPage   from './pages/DashboardPage';
import RecommendPage   from './pages/RecommendPage';
import RiskPage        from './pages/RiskPage';
import AllocationsPage from './pages/AllocationsPage';
import AuditPage       from './pages/AuditPage';

function isAuthenticated() {
  return !!localStorage.getItem('jin_auth');
}

function ProtectedLayout({ children }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">
        {children}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<Navigate to={isAuthenticated() ? '/dashboard' : '/login'} replace />} />

        <Route path="/dashboard" element={
          <ProtectedLayout><DashboardPage /></ProtectedLayout>
        } />
        <Route path="/recommend" element={
          <ProtectedLayout><RecommendPage /></ProtectedLayout>
        } />
        <Route path="/risk" element={
          <ProtectedLayout><RiskPage /></ProtectedLayout>
        } />
        <Route path="/allocations" element={
          <ProtectedLayout><AllocationsPage /></ProtectedLayout>
        } />
        <Route path="/audit" element={
          <ProtectedLayout><AuditPage /></ProtectedLayout>
        } />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
