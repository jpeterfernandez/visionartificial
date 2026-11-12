import React, { useState } from 'react';
import { useAuth } from '../context/useAuth';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Layers,
  Eye,
  Video,
  History,
  Link2,
  Sliders,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  UsersRound,
  ClipboardList,
} from 'lucide-react';

export const Sidebar: React.FC = () => {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('cardinova_sidebar_collapsed') === 'true');
  const [mobileOpen, setMobileOpen] = useState(false);

  const toggleSidebar = () => {
    setCollapsed((current) => {
      const next = !current;
      localStorage.setItem('cardinova_sidebar_collapsed', String(next));
      return next;
    });
  };

  const menuItems = [
    { id: 'dashboard', label: 'Panel General', icon: LayoutDashboard },
    { id: 'production', label: 'Producción', icon: Layers },
    { id: 'vision', label: 'Visión Artificial', icon: Eye },
    { id: 'cameras', label: 'Cámaras y Zonas', icon: Video },
    { id: 'events', label: 'Eventos e Historial', icon: History },
    ...(user?.role === 'ADMIN' ? [
      { id: 'odoo', label: 'Integración Odoo', icon: Link2 },
      { id: 'settings', label: 'Configuración', icon: Sliders },
      { id: 'users', label: 'Usuarios', icon: UsersRound },
      { id: 'audit', label: 'Auditoría', icon: ClipboardList },
    ] : []),
  ];

  return (
    <aside className={`sidebar${collapsed ? ' is-collapsed' : ''}${mobileOpen ? ' mobile-open' : ''}`}>
      <div className="sidebar-header">
        <img className="sidebar-isotype" src="/isotipo.svg" alt="" />
        <div className="sidebar-brand">
          <div className="sidebar-title">CARDINOVA</div>
        </div>
        <button
          type="button"
          className="sidebar-mobile-toggle"
          onClick={() => setMobileOpen((open) => !open)}
          aria-label={mobileOpen ? 'Cerrar menú' : 'Abrir menú'}
          aria-expanded={mobileOpen}
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
        <button
          type="button"
          className="sidebar-toggle"
          onClick={toggleSidebar}
          title={collapsed ? 'Expandir menú' : 'Contraer menú'}
          aria-label={collapsed ? 'Expandir menú' : 'Contraer menú'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      <nav className="sidebar-nav">
        {menuItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.id}
              to={`/${item.id}`}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              title={collapsed ? item.label : undefined}
              aria-label={collapsed ? item.label : undefined}
              onClick={() => setMobileOpen(false)}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <div className="user-badge">
          <span className="user-name">{user?.full_name || user?.username}</span>
          <span className="user-role">{user?.role}</span>
        </div>
        <button
          onClick={logout}
          title="Cerrar Sesión"
          aria-label="Cerrar Sesión"
          className="sidebar-logout"
        >
          <LogOut size={18} />
        </button>
      </div>
    </aside>
  );
};
