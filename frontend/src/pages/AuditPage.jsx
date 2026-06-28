import React, { useEffect, useState } from 'react';
import { getAuditLog, getSkillGaps } from '../api/client';
import LoadingSpinner from '../components/LoadingSpinner';

export default function AuditPage() {
  const [activeTab, setActiveTab] = useState('audit');
  const [auditLogs,  setAuditLogs]  = useState([]);
  const [skillGaps,  setSkillGaps]  = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState(null);

  useEffect(() => {
    Promise.allSettled([getAuditLog(), getSkillGaps()])
      .then(([a, s]) => {
        if (a.status === 'fulfilled') setAuditLogs(a.value.audit_trail || []);
        if (s.status === 'fulfilled') setSkillGaps(s.value.recent_skill_gaps || []);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">📋 Audit & Skill Gaps</h1>
          <p className="page-subtitle">Immutable AI decision trail and strategic hiring intelligence</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="badge badge-success">Audit Compliant</span>
          <span className="badge badge-violet">{auditLogs.length + skillGaps.length} Records</span>
        </div>
      </div>

      <div className="page-body">
        <div className="tabs" style={{ marginBottom: 24 }}>
          <button
            id="tab-audit"
            className={`tab ${activeTab === 'audit' ? 'active' : ''}`}
            onClick={() => setActiveTab('audit')}
          >
            🔍 AI Audit Trail
            {auditLogs.length > 0 && (
              <span style={{ marginLeft: 6, fontSize: 10, background: 'rgba(255,255,255,0.15)', borderRadius: 10, padding: '1px 6px' }}>
                {auditLogs.length}
              </span>
            )}
          </button>
          <button
            id="tab-skill-gaps"
            className={`tab ${activeTab === 'gaps' ? 'active' : ''}`}
            onClick={() => setActiveTab('gaps')}
          >
            🚨 Skill Gaps
            {skillGaps.length > 0 && (
              <span style={{ marginLeft: 6, fontSize: 10, background: 'rgba(255,255,255,0.15)', borderRadius: 10, padding: '1px 6px' }}>
                {skillGaps.length}
              </span>
            )}
          </button>
        </div>

        {loading ? (
          <LoadingSpinner text="Loading audit records..." />
        ) : error ? (
          <div className="result-box error" style={{ marginTop: 0 }}>
            <div className="result-title" style={{ color: '#f87171' }}>Error</div>
            <p style={{ fontSize: 13, color: '#fca5a5' }}>{error}</p>
          </div>
        ) : (
          <div className="fade-in">
            {/* AI Audit Trail Tab */}
            {activeTab === 'audit' && (
              <div>
                <div className="glass-card" style={{ padding: '0 0 4px', marginBottom: 20 }}>
                  <div style={{ padding: '16px 20px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                    <div className="section-title">AI Recommendation Audit Trail</div>
                    <div className="section-desc">Every AI decision is immutably logged for governance and review</div>
                  </div>
                  <div style={{ padding: '0' }}>
                    {auditLogs.length === 0 ? (
                      <div className="empty-state">
                        <div className="empty-state-icon">🔍</div>
                        <div className="empty-state-title">No audit records yet</div>
                        <div className="empty-state-desc">Use the AI Recommender to generate and log decisions</div>
                      </div>
                    ) : (
                      auditLogs.map((log, i) => (
                        <div
                          key={log.id}
                          style={{
                            padding: '18px 20px',
                            borderBottom: i < auditLogs.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                            display: 'grid',
                            gridTemplateColumns: '1fr 1fr',
                            gap: '12px 24px',
                          }}
                        >
                          <div>
                            <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 }}>Employee</div>
                            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'monospace' }}>{log.employee_id}</div>
                          </div>
                          <div>
                            <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 }}>Role Requested</div>
                            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{log.role_requested}</div>
                          </div>
                          <div>
                            <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 }}>Cosine Distance</div>
                            <span className="badge badge-violet">{log.cosine_distance?.toFixed(3)}</span>
                          </div>
                          <div>
                            <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 3 }}>Generated At</div>
                            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{new Date(log.generated_at).toLocaleString()}</div>
                          </div>
                          <div style={{ gridColumn: '1 / -1' }}>
                            <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 }}>AI Rationale</div>
                            <div style={{
                              background: 'rgba(124,58,237,0.07)',
                              border: '1px solid rgba(124,58,237,0.15)',
                              borderRadius: 8,
                              padding: '10px 14px',
                              fontSize: 12,
                              color: '#c4b5fd',
                              lineHeight: 1.7,
                              whiteSpace: 'pre-wrap'
                            }}>
                              {log.rationale_text}
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Skill Gaps Tab */}
            {activeTab === 'gaps' && (
              <div>
                {/* Summary banner */}
                <div style={{
                  background: 'linear-gradient(135deg, rgba(245,158,11,0.08), rgba(251,191,36,0.04))',
                  border: '1px solid rgba(245,158,11,0.2)',
                  borderRadius: 'var(--radius-md)',
                  padding: '14px 20px',
                  marginBottom: 20,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  fontSize: 13
                }}>
                  <span style={{ fontSize: 20 }}>⚡</span>
                  <span style={{ color: '#fcd34d' }}>
                    <strong>{skillGaps.length} skill gap{skillGaps.length !== 1 ? 's' : ''}</strong> identified by the AI engine.
                    These represent hiring opportunities where no internal match exceeded the 65% similarity threshold.
                  </span>
                </div>

                {skillGaps.length === 0 ? (
                  <div className="glass-card" style={{ padding: 20 }}>
                    <div className="empty-state">
                      <div className="empty-state-icon">✅</div>
                      <div className="empty-state-title">No skill gaps logged</div>
                      <div className="empty-state-desc">Your workforce has sufficient coverage for all requests so far</div>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                    {skillGaps.map((gap, i) => (
                      <div
                        key={gap.id}
                        className="glass-card"
                        style={{ padding: '18px 22px' }}
                      >
                        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
                          <div>
                            <span className="badge badge-warning" style={{ marginBottom: 8 }}>
                              🚨 HIRING SIGNAL
                            </span>
                            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
                              {gap.role}
                            </div>
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                            {new Date(gap.logged_at).toLocaleDateString()}
                          </div>
                        </div>
                        <div style={{
                          background: 'rgba(245,158,11,0.06)',
                          border: '1px solid rgba(245,158,11,0.15)',
                          borderRadius: 8,
                          padding: '10px 14px',
                          fontSize: 13,
                          color: '#fcd34d',
                          lineHeight: 1.6
                        }}>
                          {gap.requirements}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
