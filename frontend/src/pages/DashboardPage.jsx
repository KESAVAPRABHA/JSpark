import React, { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer
} from 'recharts';
import { getLeakage, getTeamHealth, getSupplyDemand, triggerBatchPredict } from '../api/client';
import KpiCard from '../components/KpiCard';
import LoadingSpinner from '../components/LoadingSpinner';

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div style={{
        background: '#1e0f45',
        border: '1px solid rgba(109,40,217,0.4)',
        borderRadius: 10,
        padding: '10px 14px',
        fontSize: 12,
        color: '#c4b5fd'
      }}>
        <p style={{ fontWeight: 700, marginBottom: 4, color: '#f1f0ff' }}>{label}</p>
        {payload.map((p, i) => (
          <p key={i} style={{ color: p.color }}>
            {p.name}: <strong>{p.value}</strong>
          </p>
        ))}
      </div>
    );
  }
  return null;
};

export default function DashboardPage() {
  const [leakage, setLeakage]       = useState(null);
  const [teamHealth, setTeamHealth] = useState(null);
  const [forecast, setForecast]     = useState(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchResult,  setBatchResult]  = useState(null);

  const handleBatchPredict = async () => {
    setBatchRunning(true);
    setBatchResult(null);
    try {
      const res = await triggerBatchPredict();
      setBatchResult({ ok: true, ...res });
    } catch (err) {
      setBatchResult({ ok: false, error: err.message });
    } finally {
      setBatchRunning(false);
    }
  };

  useEffect(() => {
    Promise.allSettled([getLeakage(), getTeamHealth(), getSupplyDemand()])
      .then(([l, t, f]) => {
        if (l.status === 'fulfilled') setLeakage(l.value);
        if (t.status === 'fulfilled') setTeamHealth(t.value);
        if (f.status === 'fulfilled') setForecast(f.value);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Build chart data from forecast
  const chartData = forecast?.forecast?.map(item => ({
    name: item.skill_category,
    'Supply (4w)':  item.metrics.week_4_supply  || 0,
    'Demand (4w)':  item.metrics.week_4_demand  || 0,
    'Supply (12w)': item.metrics.week_12_supply || 0,
    'Demand (12w)': item.metrics.week_12_demand || 0,
  })) || [];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Real-time resourcing intelligence overview</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            Updated: {new Date().toLocaleTimeString()}
          </span>
          <button
            id="btn-batch-predict"
            className="btn btn-secondary"
            onClick={handleBatchPredict}
            disabled={batchRunning}
            title="Run LightGBM batch prediction for all projects from WSR data"
          >
            {batchRunning ? (
              <><div className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Running...</>
            ) : (
              <>🧠 Run Batch Predict</>
            )}
          </button>
        </div>
      </div>

      {/* Batch predict result banner */}
      {batchResult && (
        <div style={{
          margin: '0 36px',
          padding: '12px 18px',
          borderRadius: 'var(--radius-md)',
          background: batchResult.ok ? 'rgba(34,211,160,0.08)' : 'rgba(244,63,94,0.08)',
          border: `1px solid ${batchResult.ok ? 'rgba(34,211,160,0.3)' : 'rgba(244,63,94,0.3)'}`,
          fontSize: 13,
          color: batchResult.ok ? '#34d399' : '#f87171',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <span>{batchResult.ok ? '✅' : '⚠️'}</span>
          {batchResult.ok
            ? `Batch complete — ${batchResult.successful}/${batchResult.projects_processed} projects scored. ${batchResult.failed > 0 ? `${batchResult.failed} failed.` : ''}`
            : `Batch predict failed: ${batchResult.error}`
          }
        </div>
      )}

      <div className="page-body">
        {loading ? (
          <LoadingSpinner text="Fetching resourcing intelligence..." />
        ) : (
          <div className="fade-in">
            {/* KPI Row */}
            <div className="kpi-grid">
              <KpiCard
                icon="💸"
                label="Weekly Revenue Leakage"
                value={leakage?.estimated_weekly_revenue_leakage_usd ?? '—'}
                sub={leakage?.calculation_method}
                variant="danger"
              />
              <KpiCard
                icon="👥"
                label="Shadow Resources"
                value={leakage?.shadow_resource_count ?? '—'}
                sub={`${leakage?.weekly_unbilled_hours ?? 0} unbilled hrs/week`}
                variant="warning"
              />
              <KpiCard
                icon="📈"
                label="Skill Categories Tracked"
                value={forecast?.forecast?.length ?? '—'}
                sub="Across 4/8/12-week horizons"
                variant="info"
              />
              <KpiCard
                icon="🏆"
                label="PMs on Leaderboard"
                value={teamHealth?.leaderboard?.length ?? '—'}
                sub="Composite health scored"
                variant="violet"
              />
            </div>

            {/* Leakage Action Banner */}
            {leakage?.action_prompt && (
              <div style={{
                background: 'linear-gradient(135deg, rgba(244,63,94,0.1), rgba(251,113,133,0.05))',
                border: '1px solid rgba(244,63,94,0.25)',
                borderRadius: 'var(--radius-md)',
                padding: '14px 20px',
                marginBottom: 28,
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                fontSize: 13.5,
                color: '#fca5a5'
              }}>
                <span style={{ fontSize: 20 }}>🚨</span>
                <span><strong>Action Required:</strong> {leakage.action_prompt}</span>
              </div>
            )}

            {/* Two column: Supply/Demand chart + PM Leaderboard */}
            <div className="two-col-grid">
              {/* Supply vs Demand Forecast */}
              <div className="glass-card" style={{ padding: 24 }}>
                <div className="section-header">
                  <div>
                    <div className="section-title">📉 Supply vs Demand Forecast</div>
                    <div className="section-desc">4-week and 12-week horizon by skill domain</div>
                  </div>
                </div>
                {chartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis
                        dataKey="name"
                        tick={{ fill: '#8b7cc8', fontSize: 10 }}
                        angle={-25}
                        textAnchor="end"
                        interval={0}
                      />
                      <YAxis tick={{ fill: '#8b7cc8', fontSize: 10 }} />
                      <Tooltip content={<CustomTooltip />} />
                      <Legend wrapperStyle={{ fontSize: 11, color: '#8b7cc8' }} />
                      <Bar dataKey="Supply (4w)"  fill="#7c3aed" radius={[4,4,0,0]} />
                      <Bar dataKey="Demand (4w)"  fill="#c026d3" radius={[4,4,0,0]} />
                      <Bar dataKey="Supply (12w)" fill="#4c1d95" radius={[4,4,0,0]} />
                      <Bar dataKey="Demand (12w)" fill="#db2777" radius={[4,4,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="empty-state">
                    <div className="empty-state-icon">📊</div>
                    <div className="empty-state-title">No forecast data</div>
                    <div className="empty-state-desc">Ensure projects and allocations are seeded in the database.</div>
                  </div>
                )}
              </div>

              {/* Team Health Leaderboard */}
              <div className="glass-card" style={{ padding: 24 }}>
                <div className="section-header">
                  <div>
                    <div className="section-title">🏆 PM Health Leaderboard</div>
                    <div className="section-desc">Composite score: 60% utilization + 40% risk</div>
                  </div>
                </div>
                {teamHealth?.leaderboard?.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {teamHealth.leaderboard.slice(0, 7).map((pm, i) => (
                      <div
                        key={pm.project_manager}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 12,
                          padding: '10px 14px',
                          background: 'rgba(255,255,255,0.03)',
                          borderRadius: 10,
                          border: '1px solid rgba(255,255,255,0.05)',
                        }}
                      >
                        <span style={{
                          width: 22,
                          height: 22,
                          borderRadius: '50%',
                          background: i === 0
                            ? 'linear-gradient(135deg,#f59e0b,#fbbf24)'
                            : i === 1
                              ? 'linear-gradient(135deg,#94a3b8,#cbd5e1)'
                              : 'rgba(255,255,255,0.08)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 10,
                          fontWeight: 700,
                          color: i < 2 ? '#1a0a3d' : '#8b7cc8',
                          flexShrink: 0,
                        }}>
                          {i + 1}
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {pm.project_manager}
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                            {pm.total_projects} projects · {pm.total_resources} resources
                          </div>
                        </div>
                        {/* Score bar */}
                        <div style={{ width: 80 }}>
                          <div style={{ height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 4, overflow: 'hidden' }}>
                            <div style={{
                              width: `${pm.composite_score}%`,
                              height: '100%',
                              background: pm.composite_score >= 70
                                ? 'linear-gradient(90deg,#22d3a0,#34d399)'
                                : pm.composite_score >= 50
                                  ? 'linear-gradient(90deg,#f59e0b,#fbbf24)'
                                  : 'linear-gradient(90deg,#f43f5e,#fb7185)',
                              borderRadius: 4
                            }} />
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'right', marginTop: 2 }}>
                            {pm.composite_score}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <div className="empty-state-icon">👤</div>
                    <div className="empty-state-title">No PM data</div>
                    <div className="empty-state-desc">No projects or allocations found in the database.</div>
                  </div>
                )}
              </div>
            </div>

            {/* Error notice */}
            {error && (
              <div style={{
                marginTop: 20,
                padding: '12px 16px',
                background: 'rgba(244,63,94,0.08)',
                border: '1px solid rgba(244,63,94,0.2)',
                borderRadius: 10,
                fontSize: 13,
                color: '#fca5a5'
              }}>
                ⚠️ Some data could not be loaded. Is the backend running? <code style={{ fontSize: 11 }}>{error}</code>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
