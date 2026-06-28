import React, { useState, useEffect } from 'react';
import { postRecommend, getRoles } from '../api/client';

export default function RecommendPage() {
  const [role, setRole]           = useState('');
  const [requirements, setReqs]   = useState('');
  const [result, setResult]       = useState(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState(null);
  const [roles, setRoles]         = useState([]);
  const [rolesLoading, setRolesLoading] = useState(true);

  useEffect(() => {
    getRoles()
      .then(res => setRoles(res.roles || []))
      .catch(() => setRoles([]))  // silently fall back if backend is down
      .finally(() => setRolesLoading(false));
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await postRecommend(requirements, role);
      setResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const rationaleLines = result?.rationale
    ? result.rationale
        .split('\n')
        .map(l => l.replace(/^•\s*/, '').replace(/^\*\s*/, '').trim())
        .filter(Boolean)
    : [];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">🤖 AI Resource Recommender</h1>
          <p className="page-subtitle">Find the best-matched employee using vector similarity + Gemini rationale</p>
        </div>
      </div>

      <div className="page-body">
        <div className="two-col-grid">
          {/* Form */}
          <div className="glass-card" style={{ padding: 28 }}>
            <div className="section-title" style={{ marginBottom: 20 }}>Define Project Requirements</div>
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label" htmlFor="input-role">Required Role / Designation</label>
                <select
                  id="input-role"
                  className="form-select"
                  value={role}
                  onChange={e => setRole(e.target.value)}
                  required
                  disabled={rolesLoading}
                >
                  <option value="">
                    {rolesLoading ? 'Loading roles from database...' : roles.length === 0 ? 'No roles found — seed the DB first' : 'Select a role...'}
                  </option>
                  {roles.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
                {roles.length > 0 && (
                  <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                    {roles.length} designations found in database
                  </span>
                )}
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="input-requirements">Project Requirements</label>
                <textarea
                  id="input-requirements"
                  className="form-textarea"
                  placeholder="Describe the skills, technologies, and experience needed...&#10;e.g. Expert in React, Node.js, and cloud architecture. Must have 5+ years of fintech experience."
                  value={requirements}
                  onChange={e => setReqs(e.target.value)}
                  rows={6}
                  required
                  minLength={10}
                />
                <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                  Minimum 10 characters required for semantic search
                </span>
              </div>

              <button
                id="btn-find-resource"
                type="submit"
                className="btn btn-primary"
                disabled={loading || !role || requirements.length < 10}
                style={{ width: '100%', justifyContent: 'center' }}
              >
                {loading ? (
                  <>
                    <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                    Searching vector database...
                  </>
                ) : (
                  <>🔍 Find Best Match</>
                )}
              </button>
            </form>
          </div>

          {/* Result Panel */}
          <div>
            {/* How it works */}
            <div className="glass-card" style={{ padding: 22, marginBottom: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 12 }}>
                ⚙️ How It Works
              </div>
              {[
                { step: '1', desc: 'Your requirements are embedded and queried against ChromaDB (cosine similarity)' },
                { step: '2', desc: 'Only employees with the exact designation match are considered' },
                { step: '3', desc: 'Distance > 0.35 triggers a "Hire Signal" — no close enough match exists' },
                { step: '4', desc: 'Gemini generates a human-readable rationale for the top match' },
              ].map(({ step, desc }) => (
                <div key={step} style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
                  <span style={{
                    width: 20, height: 20, borderRadius: '50%',
                    background: 'linear-gradient(135deg,var(--color-violet-bright),var(--color-magenta-hot))',
                    color: 'white', fontSize: 10, fontWeight: 700,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0
                  }}>{step}</span>
                  <p style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>{desc}</p>
                </div>
              ))}
            </div>

            {/* Result */}
            {error && (
              <div className="result-box error">
                <div className="result-title" style={{ color: '#f87171' }}>⚠️ Error</div>
                <p style={{ fontSize: 13, color: '#fca5a5' }}>{error}</p>
              </div>
            )}

            {result && result.status === 'MATCH_FOUND' && (
              <div className="result-box match-found fade-in">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                  <div className="result-title" style={{ color: '#34d399' }}>✅ Match Found</div>
                  <span className="badge badge-success">DEPLOY</span>
                </div>
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 4 }}>Employee ID</div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary)', letterSpacing: -0.3 }}>
                    {result.employee_id}
                  </div>
                </div>
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 4 }}>Cosine Distance</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{
                      height: 6, flex: 1,
                      background: 'rgba(255,255,255,0.08)',
                      borderRadius: 3, overflow: 'hidden'
                    }}>
                      <div style={{
                        width: `${(1 - result.cosine_distance) * 100}%`,
                        height: '100%',
                        background: 'linear-gradient(90deg,#22d3a0,#34d399)',
                        borderRadius: 3
                      }} />
                    </div>
                    <span style={{ fontSize: 13, color: '#34d399', fontWeight: 700, minWidth: 36 }}>
                      {result.cosine_distance}
                    </span>
                  </div>
                </div>
                {rationaleLines.length > 0 && (
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 8 }}>AI Rationale</div>
                    <ul className="rationale-list">
                      {rationaleLines.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {result && result.status === 'NO_MATCH_FOUND' && (
              <div className="result-box no-match fade-in">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                  <div className="result-title" style={{ color: '#fbbf24' }}>🚨 No Match — Hire Signal</div>
                  <span className="badge badge-warning">INITIATE HIRE</span>
                </div>
                <p style={{ fontSize: 13, color: '#fcd34d', lineHeight: 1.6 }}>
                  {result.reason || result.signal}
                </p>
                <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
                  This gap has been logged in the Strategic Hiring Aggregator for HR review.
                </p>
              </div>
            )}

            {!result && !error && !loading && (
              <div className="empty-state">
                <div className="empty-state-icon">🔍</div>
                <div className="empty-state-title">Ready to search</div>
                <div className="empty-state-desc">Fill in the form and click Find Best Match</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
