import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';

const NAV_ITEMS = [
  { to: '/dashboard',   icon: '📊', label: 'Dashboard'       },
  { to: '/recommend',   icon: '🤖', label: 'AI Recommender'  },
  { to: '/risk',        icon: '⚠️', label: 'Risk Checker'    },
  { to: '/allocations', icon: '👥', label: 'Allocations'     },
  { to: '/audit',       icon: '📋', label: 'Audit & Gaps'    },
];

export default function Sidebar() {
  const navigate = useNavigate();
  const raw = localStorage.getItem('jin_auth');
  const user = raw ? JSON.parse(raw) : { name: 'Resource Manager', email: 'rm@jin.apps' };

  const handleLogout = () => {
    localStorage.removeItem('jin_auth');
    navigate('/login');
  };

  const initials = user.name
    .split(' ')
    .map(w => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">J</div>
        <div>
          <div className="sidebar-logo-text">JIN Apps</div>
          <div className="sidebar-logo-sub">Self Service Portal</div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        <div className="nav-section-label">Navigation</div>
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            id={`nav-${item.label.toLowerCase().replace(/\s+/g, '-')}`}
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="sidebar-avatar">{initials}</div>
          <div className="sidebar-user-info">
            <div className="sidebar-user-name">{user.name}</div>
            <div className="sidebar-user-role">Resource Manager</div>
          </div>
          <button
            id="btn-logout"
            className="logout-btn"
            onClick={handleLogout}
            title="Sign out"
          >
            ⬡
          </button>
        </div>
      </div>
    </aside>
  );
}
