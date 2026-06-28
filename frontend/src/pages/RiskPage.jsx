import React, { useState } from 'react';
import { postPredictRisk } from '../api/client';

const STATUS_OPTIONS = ['NO_COLOR', 'GREEN', 'AMBER', 'RED'];

const STATUS_COLORS = {
  NO_COLOR: '#8b7cc8',
  GREEN:    '#22d3a0',
  AMBER:    '#f59e0b',
  RED:      '#f43f5e',
};

// SVG arc risk gauge
function RiskGauge({ probability }) {
  const pct = Math.min(1, Math.max(0, probability));
  const angle = pct * 180; // 0 = left, 180 = right
  const rad = (angle - 90) * (Math.PI / 180);
  const cx = 100, cy = 100, r = 80;
  const nx = cx + r * Math.cos(rad);
  const ny = cy + r * Math.sin(rad);

  const color = pct >= 0.66
    ? '#f43f5e'
    : pct >= 0.33
      ? '#f59e0b'
      : '#22d3a0';

  return (
    <svg viewBox="0 0 200 110" width="200" height="110">
      {/* Background arc */}
      <path
        d="M20 100 A80 80 0 0 1 180 100"
        fill="none"
        stroke="rgba(255,255,255,0.06)"
        strokeWidth="16"
        strokeLinecap="round"
      />
      {/* Colored fill arc */}
      <path
        d="M20 100 A80 80 0 0 1 180 100"
        fill="none"
        stroke="url(#gaugeGrad)"
        strokeWidth="16"
        strokeLinecap="round"
        strokeDasharray={`${pct * 251.2} 251.2`}
      />
      {/* Needle */}
      <line
        x1={cx} y1={cy}
        x2={nx} y2={ny}
        stroke={color}
        strokeWidth="3"
        strokeLinecap="round"
      />
      <circle cx={cx} cy={cy} r="5" fill={color} />
      {/* Labels */}
      <text x="22" y="114" fontSize="9" fill="#8b7cc8" textAnchor="middle">LOW</text>
      <text x="100" y="22" fontSize="9" fill="#8b7cc8" textAnchor="middle">MED</text>
      <text x="178" y="114" fontSize="9" fill="#8b7cc8" textAnchor="middle">HIGH</text>
      {/* Probability text */}
      <text x="100" y="95" fontSize="22" fontWeight="800" fill={color} textAnchor="middle">
        {Math.round(pct * 100)}%
      </text>
      <defs>
        <linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%"   stopColor="#22d3a0" />
          <stop offset="50%"  stopColor="#f59e0b" />
          <stop offset="100%" stopColor="#f43f5e" />
        </linearGradient>
      </defs>
    </svg>
  );
}

export default function RiskPage() {
  const [quality, setQuality] = useState('GREEN');
  const [csat,    setCsat   ] = useState('GREEN');
  const [team,    setTeam   ] = useState('GREEN');
  const [result,  setResult ] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError  ] = useState(null);

  const handlePredict = async (e) => {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await postPredictRisk(quality, csat, team);
      setResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const tierColor = result
    ? result.risk_tier === 'HIGH'
      ? 'var(--color-danger)'
      : result.risk_tier === 'MEDIUM'
        ? 'var(--color-warning)'
        : 'var(--color-success)'
    : null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">⚠️ Project Risk Checker</h1>
          <p className="page-subtitle">SHAP-powered LightGBM health prediction with root-cause explainability</p>
        </div>
      </div>

      <div className="page-body">
        <div className="two-col-grid">
          {/* Input form */}
          <div className="glass-card" style={{ padding: 28 }}>
            <div className="section-title" style={{ marginBottom: 6 }}>Project Health Signals</div>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 24 }}>
              Select the current RAG (Red-Amber-Green) status for each dimension.
            </p>
            <form onSubmit={handlePredict}>
              {[
                { label: 'Quality Status',  value: quality, setter: setQuality, id: 'quality_status', icon: '🔬' },
                { label: 'CSAT Status',     value: csat,    setter: setCsat,    id: 'csat_status',    icon: '😊' },
                { label: 'Team Status',     value: team,    setter: setTeam,    id: 'team_status',    icon: '👥' },
              ].map(({ label, value, setter, id, icon }) => (
                <div className="form-group" key={id}>
                  <label className="form-label" htmlFor={id}>
                    {icon} {label}
                  </label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {STATUS_OPTIONS.map(opt => (
                      <button
                        key={opt}
                        type="button"
                        id={`${id}-${opt.toLowerCase()}`}
                        onClick={() => setter(opt)}
                        style={{
                          flex: 1,
                          padding: '8px 4px',
                          borderRadius: 8,
                          border: value === opt
                            ? `1.5px solid ${STATUS_COLORS[opt]}`
                            : '1px solid rgba(255,255,255,0.08)',
                          background: value === opt
                            ? `${STATUS_COLORS[opt]}22`
                            : 'rgba(255,255,255,0.03)',
                          color: value === opt ? STATUS_COLORS[opt] : 'var(--text-dim)',
                          fontSize: 11,
                          fontWeight: value === opt ? 700 : 400,
                          cursor: 'pointer',
                          transition: 'all 0.15s ease',
                        }}
                      >
                        {opt === 'NO_COLOR' ? '—' : opt}
                      </button>
                    ))}
                  </div>
                </div>
              ))}

              <button
                id="btn-predict-risk"
                type="submit"
                className="btn btn-primary"
                disabled={loading}
                style={{ width: '100%', justifyContent: 'center', marginTop: 8 }}
              >
                {loading ? (
                  <>
                    <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                    Running ML model...
                  </>
                ) : '🧠 Predict Risk'}
              </button>
            </form>
          </div>

          {/* Result panel */}
          <div>
            {error && (
              <div className="result-box error">
                <div className="result-title" style={{ color: '#f87171' }}>Error</div>
                <p style={{ fontSize: 13, color: '#fca5a5' }}>{error}</p>
              </div>
            )}

            {result && (
              <div className="glass-card fade-in" style={{ padding: 28 }}>
                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <RiskGauge probability={result.risk_probability} />
                </div>

                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <span style={{
                    fontSize: 28, fontWeight: 800, color: tierColor, letterSpacing: -0.5
                  }}>
                    {result.risk_tier} RISK
                  </span>
                </div>

                <div style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: `1px solid ${tierColor}33`,
                  borderRadius: 12,
                  padding: '14px 18px',
                  marginBottom: 14
                }}>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>Recommended Action</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {result.recommended_action}
                  </div>
                </div>

                <div style={{
                  background: 'rgba(124,58,237,0.08)',
                  border: '1px solid rgba(124,58,237,0.2)',
                  borderRadius: 12,
                  padding: '14px 18px',
                }}>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    🔬 SHAP Root Cause
                  </div>
                  <div style={{ fontSize: 13.5, color: '#c4b5fd', lineHeight: 1.6 }}>
                    {result.root_cause_explainer}
                  </div>
                </div>
              </div>
            )}

            {!result && !error && (
              <div className="glass-card" style={{ padding: 28 }}>
                <div className="empty-state">
                  <div className="empty-state-icon">🧠</div>
                  <div className="empty-state-title">Set Health Signals</div>
                  <div className="empty-state-desc">
                    Select RAG statuses and click Predict Risk to run the LightGBM model
                  </div>
                </div>
                <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {[
                    { label: 'Model', value: 'LightGBM (LGBM) — trained on historical project data' },
                    { label: 'Explainability', value: 'SHAP TreeExplainer — identifies root cause feature' },
                    { label: 'Threshold', value: 'Mathematically optimal, read from optimal_threshold.txt' },
                  ].map(({ label, value }) => (
                    <div key={label} style={{
                      display: 'flex', gap: 10, fontSize: 12,
                      padding: '8px 12px',
                      background: 'rgba(255,255,255,0.02)',
                      borderRadius: 8
                    }}>
                      <span style={{ color: 'var(--color-magenta)', fontWeight: 600, minWidth: 100 }}>{label}</span>
                      <span style={{ color: 'var(--text-muted)' }}>{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
