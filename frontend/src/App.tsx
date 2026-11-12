import React, { lazy, Suspense } from 'react';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/useAuth';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { RefreshCw } from 'lucide-react';

const LoginView = lazy(() => import('./views/LoginView').then(module => ({ default: module.LoginView })));
const DashboardView = lazy(() => import('./views/DashboardView').then(module => ({ default: module.DashboardView })));
const ProductionView = lazy(() => import('./views/ProductionView').then(module => ({ default: module.ProductionView })));
const VisionView = lazy(() => import('./views/VisionView').then(module => ({ default: module.VisionView })));
const CamerasView = lazy(() => import('./views/CamerasView').then(module => ({ default: module.CamerasView })));
const EventsView = lazy(() => import('./views/EventsView').then(module => ({ default: module.EventsView })));
const OdooView = lazy(() => import('./views/OdooView').then(module => ({ default: module.OdooView })));
const SettingsView = lazy(() => import('./views/SettingsView').then(module => ({ default: module.SettingsView })));
const UsersView = lazy(() => import('./views/UsersView').then(module => ({ default: module.UsersView })));
const AuditView = lazy(() => import('./views/AuditView').then(module => ({ default: module.AuditView })));

const AppContent: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: '#f8fafc'
      }}>
        <RefreshCw className="animate-spin" size={32} style={{ color: 'var(--primary)' }} />
        <p style={{ marginTop: '12px', fontSize: '0.9rem', color: '#64748b' }}>Iniciando sesión segura...</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Suspense fallback={<div className="view-container">Cargando...</div>}><LoginView /></Suspense>;
  }

  return (
    <div className="app-container">
      <Sidebar />
      <main className="main-content">
        <Suspense fallback={<div className="view-container">Cargando vista...</div>}>
          <Routes>
            <Route path="/dashboard" element={<DashboardView />} />
            <Route path="/production" element={<ProductionView />} />
            <Route path="/vision" element={<VisionView />} />
            <Route path="/cameras" element={<CamerasView />} />
            <Route path="/events" element={<EventsView />} />
            <Route path="/odoo" element={<OdooView />} />
            <Route path="/settings" element={<SettingsView />} />
            <Route path="/users" element={<UsersView />} />
            <Route path="/audit" element={<AuditView />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
};

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </AuthProvider>
  );
}
