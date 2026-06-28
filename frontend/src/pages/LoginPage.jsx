import React from 'react';
import { useNavigate } from 'react-router-dom';
import './LoginPage.css';

// Microsoft Windows logo SVG
const MicrosoftLogo = () => (
  <svg width="20" height="20" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="9" height="9" fill="#f25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
    <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
  </svg>
);

// JIN leaf logo SVG
const JinLogo = () => (
  <svg width="52" height="60" viewBox="0 0 52 60" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M26 4 C26 4, 10 16, 10 32 C10 44 18 52 26 56 C34 52 42 44 42 32 C42 16 26 4 26 4Z" fill="url(#leaf1)" opacity="0.9"/>
    <path d="M26 12 C26 12, 16 22, 17 34 C18 42 22 48 26 52" stroke="rgba(255,255,255,0.3)" strokeWidth="1.5" fill="none"/>
    <path d="M18 8 C18 8, 28 12, 32 24 C35 34 30 44 26 50" fill="url(#leaf2)" opacity="0.7"/>
    <defs>
      <linearGradient id="leaf1" x1="10" y1="4" x2="42" y2="56" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#c4b5fd"/>
        <stop offset="100%" stopColor="#a78bfa"/>
      </linearGradient>
      <linearGradient id="leaf2" x1="18" y1="8" x2="32" y2="50" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#e9d5ff"/>
        <stop offset="100%" stopColor="#c4b5fd"/>
      </linearGradient>
    </defs>
  </svg>
);

// Floating geometric shapes for left panel
const shapes = [
  { type: 'circle',   size: 56,  top: '8%',  left: '8%',  opacity: 0.15, delay: '0s',   duration: '6s'  },
  { type: 'triangle', size: 40,  top: '14%', left: '62%', opacity: 0.12, delay: '1s',   duration: '7s'  },
  { type: 'square',   size: 32,  top: '50%', left: '5%',  opacity: 0.10, delay: '0.5s', duration: '8s'  },
  { type: 'diamond',  size: 28,  top: '65%', left: '60%', opacity: 0.14, delay: '2s',   duration: '6.5s'},
  { type: 'circle',   size: 18,  top: '30%', left: '78%', opacity: 0.18, delay: '1.5s', duration: '5s'  },
  { type: 'circle',   size: 10,  top: '80%', left: '30%', opacity: 0.22, delay: '0.8s', duration: '9s'  },
  { type: 'circle',   size: 8,   top: '22%', left: '42%', opacity: 0.25, delay: '0.2s', duration: '7s'  },
  { type: 'dot',      size: 6,   top: '70%', left: '12%', opacity: 0.35, delay: '1.2s', duration: '5.5s'},
  { type: 'dot',      size: 6,   top: '45%', left: '52%', opacity: 0.28, delay: '2.5s', duration: '6s'  },
];

function Shape({ shape }) {
  const baseStyle = {
    position: 'absolute',
    top: shape.top,
    left: shape.left,
    opacity: shape.opacity,
    animation: `float ${shape.duration} ease-in-out ${shape.delay} infinite`,
  };

  if (shape.type === 'circle' || shape.type === 'dot') {
    return (
      <div style={{
        ...baseStyle,
        width: shape.size,
        height: shape.size,
        borderRadius: '50%',
        border: '1.5px solid rgba(196,181,253,0.8)',
        background: shape.type === 'dot' ? 'rgba(196,181,253,0.5)' : 'transparent',
      }} />
    );
  }
  if (shape.type === 'square') {
    return (
      <div style={{
        ...baseStyle,
        width: shape.size,
        height: shape.size,
        transform: 'rotate(20deg)',
        border: '1.5px solid rgba(196,181,253,0.8)',
      }} />
    );
  }
  if (shape.type === 'diamond') {
    return (
      <div style={{
        ...baseStyle,
        width: shape.size,
        height: shape.size,
        transform: 'rotate(45deg)',
        border: '1.5px solid rgba(196,181,253,0.8)',
      }} />
    );
  }
  if (shape.type === 'triangle') {
    return (
      <div style={{
        ...baseStyle,
        width: 0,
        height: 0,
        borderLeft: `${shape.size / 2}px solid transparent`,
        borderRight: `${shape.size / 2}px solid transparent`,
        borderBottom: `${shape.size}px solid rgba(196,181,253,0.6)`,
        border: 'none',
        borderLeft: `${shape.size / 2}px solid transparent`,
        borderRight: `${shape.size / 2}px solid transparent`,
        borderBottom: `${shape.size}px solid rgba(196,181,253,0.18)`,
      }} />
    );
  }
  return null;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = React.useState(false);

  const handleMicrosoftLogin = () => {
    setLoading(true);
    // Simulate Microsoft SSO flow
    setTimeout(() => {
      localStorage.setItem('jin_auth', JSON.stringify({ name: 'Resource Manager', email: 'rm@jin.apps' }));
      navigate('/dashboard');
    }, 1400);
  };

  return (
    <div className="login-page">
      {/* LEFT PANEL */}
      <div className="login-left">
        {/* Floating shapes */}
        {shapes.map((s, i) => <Shape key={i} shape={s} />)}

        {/* Glowing orb behind logo */}
        <div className="login-left-orb" />

        {/* Logo */}
        <div className="login-logo-wrap">
          <JinLogo />
          <span className="login-brand-name">JIN Apps</span>
        </div>
      </div>

      {/* CURVED DIVIDER */}
      <div className="login-divider">
        <svg viewBox="0 0 60 400" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M60 0 Q0 200 60 400 L60 0Z" fill="#4c1d95" opacity="0.4"/>
          <path d="M54 0 Q-4 200 54 400" stroke="url(#divGrad)" strokeWidth="3" fill="none"/>
          <defs>
            <linearGradient id="divGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#7c3aed" stopOpacity="0"/>
              <stop offset="30%" stopColor="#c026d3" stopOpacity="1"/>
              <stop offset="70%" stopColor="#7c3aed" stopOpacity="1"/>
              <stop offset="100%" stopColor="#7c3aed" stopOpacity="0"/>
            </linearGradient>
          </defs>
        </svg>
      </div>

      {/* RIGHT PANEL */}
      <div className="login-right">
        <div className="login-right-content">
          <h1 className="login-heading">Welcome to JIN</h1>
          <p className="login-subheading">People's Self Service Portal</p>

          <button
            id="btn-microsoft-login"
            className={`ms-login-btn ${loading ? 'loading' : ''}`}
            onClick={handleMicrosoftLogin}
            disabled={loading}
          >
            {loading ? (
              <>
                <div className="ms-btn-spinner" />
                <span>Signing in...</span>
              </>
            ) : (
              <>
                <span className="ms-logo-wrap">
                  <MicrosoftLogo />
                </span>
                <span>Login with Microsoft</span>
              </>
            )}
          </button>

          <p className="login-footer-note">
            By continuing, you agree to your organization's terms of use.
          </p>
        </div>
      </div>
    </div>
  );
}
