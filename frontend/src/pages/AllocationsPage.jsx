import React, { useEffect, useState } from 'react';
import { getAllocations, getRiskScores, postAllocate } from '../api/client';
import LoadingSpinner from '../components/LoadingSpinner';

const STATUS_BADGE = {
  BILLABLE:             'badge-success',
  ALLOCATED:            'badge-success',
  SHADOW:               'badge-warning',
  UNBILLED:             'badge-warning',
  'PRESENCE UNVERIFIED':'badge-danger',
};

export default function AllocationsPage() {
  const [allocations, setAllocations] = useState([]);
  const [riskScores,  setRiskScores]  = useState([]);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(null);
  const [showModal,   setShowModal]   = useState(false);
  const [filter,      setFilter]      = useState('ALL');

  // Modal state
  const [empId,  setEmpId]  = useState('');
  const [projId, setProjId] = useState('');
  const [pct,    setPct]    = useState(100);
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg,  setSubmitMsg]  = useState(null);
  const [submitErr,  setSubmitErr]  = useState(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [a, r] = await Promise.all([getAllocations(), getRiskScores()]);
      setAllocations(a.data || []);
      setRiskScores(r.active_risk_assessments || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleAllocate = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setSubmitMsg(null);
    setSubmitErr(null);
    try {
      const res = await postAllocate(empId, projId, Number(pct));
      setSubmitMsg(res.message);
      await fetchData();
      setTimeout(() => {
        setShowModal(false);
        setSubmitMsg(null);
        setEmpId(''); setProjId(''); setPct(100);
      }, 1500);
    } catch (err) {
      setSubmitErr(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const filtered = filter === 'ALL'
    ? allocations
    : allocations.filter(a => a.status?.toUpperCase() === filter);

  const statuses = ['ALL', 'BILLABLE', 'SHADOW', 'UNBILLED'];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">👥 Resource Allocations</h1>
          <p className="page-subtitle">View and manage all resource allocations with capacity guard</p>
        </div>
        <button
          id="btn-open-allocate"
          className="btn btn-primary"
          onClick={() => setShowModal(true)}
        >
          + Allocate Resource
        </button>
      </div>

      <div className="page-body">
        {loading ? (
          <LoadingSpinner text="Loading allocations..." />
        ) : error ? (
          <div className="result-box error">
            <div className="result-title" style={{ color: '#f87171' }}>Error</div>
            <p style={{ fontSize: 13, color: '#fca5a5' }}>{error}</p>
          </div>
        ) : (
          <div className="fade-in">
            {/* Filter tabs */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              <div className="tabs">
                {statuses.map(s => (
                  <button
                    key={s}
                    id={`filter-${s.toLowerCase()}`}
                    className={`tab ${filter === s ? 'active' : ''}`}
                    onClick={() => setFilter(s)}
                  >
                    {s}
                    <span style={{
                      marginLeft: 6,
                      fontSize: 10,
                      background: 'rgba(255,255,255,0.1)',
                      borderRadius: 10,
                      padding: '1px 6px'
                    }}>
                      {s === 'ALL'
                        ? allocations.length
                        : allocations.filter(a => a.status?.toUpperCase() === s).length
                      }
                    </span>
                  </button>
                ))}
              </div>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {filtered.length} record{filtered.length !== 1 ? 's' : ''}
              </span>
            </div>

            {/* Allocations table */}
            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Employee ID</th>
                    <th>Project ID</th>
                    <th>Status</th>
                    <th>Allocation %</th>
                    <th>Start Date</th>
                    <th>End Date</th>
                    <th>Designation</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={7} style={{ textAlign: 'center', padding: '40px', color: 'var(--text-dim)' }}>
                        No allocations found
                      </td>
                    </tr>
                  ) : (
                    filtered.map(a => (
                      <tr key={a.id}>
                        <td style={{ fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'monospace', fontSize: 12 }}>
                          {a.employee_id}
                        </td>
                        <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{a.project_id}</td>
                        <td>
                          <span className={`badge ${STATUS_BADGE[a.status?.toUpperCase()] || 'badge-muted'}`}>
                            {a.status}
                          </span>
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{
                              width: 48, height: 4,
                              background: 'rgba(255,255,255,0.08)',
                              borderRadius: 2, overflow: 'hidden'
                            }}>
                              <div style={{
                                width: `${a.percentage}%`,
                                height: '100%',
                                background: a.percentage === 100
                                  ? 'linear-gradient(90deg,#22d3a0,#34d399)'
                                  : 'linear-gradient(90deg,#7c3aed,#a855f7)',
                                borderRadius: 2
                              }} />
                            </div>
                            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{a.percentage}%</span>
                          </div>
                        </td>
                        <td style={{ fontSize: 12 }}>
                          {a.start_date ? new Date(a.start_date).toLocaleDateString() : '—'}
                        </td>
                        <td style={{ fontSize: 12 }}>
                          {a.end_date ? new Date(a.end_date).toLocaleDateString() : '—'}
                        </td>
                        <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                          {a.employee?.designation || '—'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Risk Scores summary */}
            {riskScores.length > 0 && (
              <div style={{ marginTop: 28 }}>
                <div className="section-header">
                  <div>
                    <div className="section-title">📊 Project Risk Scores</div>
                    <div className="section-desc">ML-computed risk probabilities from the prediction engine</div>
                  </div>
                </div>
                <div className="table-wrapper">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Project ID</th>
                        <th>Risk Probability</th>
                        <th>At Risk</th>
                        <th>Primary Driver</th>
                        <th>Calculated At</th>
                      </tr>
                    </thead>
                    <tbody>
                      {riskScores.map(rs => (
                        <tr key={rs.id}>
                          <td style={{ fontWeight: 600, fontSize: 12, fontFamily: 'monospace' }}>{rs.project_id}</td>
                          <td>
                            <span style={{ color: rs.risk_probability >= 0.6 ? '#f87171' : rs.risk_probability >= 0.3 ? '#fbbf24' : '#34d399', fontWeight: 700 }}>
                              {Math.round(rs.risk_probability * 100)}%
                            </span>
                          </td>
                          <td>
                            <span className={`badge ${rs.is_at_risk ? 'badge-danger' : 'badge-success'}`}>
                              {rs.is_at_risk ? 'YES' : 'NO'}
                            </span>
                          </td>
                          <td style={{ fontSize: 12 }}>{rs.primary_driver}</td>
                          <td style={{ fontSize: 12 }}>{new Date(rs.calculated_at).toLocaleDateString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Allocate Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <div className="modal-title">Allocate Resource</div>
              <button
                id="btn-close-modal"
                className="modal-close"
                onClick={() => setShowModal(false)}
              >✕</button>
            </div>

            <form onSubmit={handleAllocate}>
              <div className="form-group">
                <label className="form-label" htmlFor="modal-emp-id">Employee ID</label>
                <input
                  id="modal-emp-id"
                  className="form-input"
                  placeholder="e.g. EMP001"
                  value={empId}
                  onChange={e => setEmpId(e.target.value)}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="modal-proj-id">Project ID</label>
                <input
                  id="modal-proj-id"
                  className="form-input"
                  placeholder="e.g. PROJ042"
                  value={projId}
                  onChange={e => setProjId(e.target.value)}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="modal-pct">
                  Allocation Percentage: <strong style={{ color: 'var(--color-violet-bright)' }}>{pct}%</strong>
                </label>
                <input
                  id="modal-pct"
                  type="range"
                  min={10}
                  max={100}
                  step={5}
                  value={pct}
                  onChange={e => setPct(e.target.value)}
                  style={{ width: '100%', accentColor: 'var(--color-violet-bright)', cursor: 'pointer' }}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-dim)' }}>
                  <span>10%</span><span>50%</span><span>100%</span>
                </div>
              </div>

              {submitMsg && (
                <div style={{ padding: '10px 14px', background: 'rgba(34,211,160,0.1)', border: '1px solid rgba(34,211,160,0.3)', borderRadius: 8, fontSize: 13, color: '#34d399', marginBottom: 14 }}>
                  ✅ {submitMsg}
                </div>
              )}
              {submitErr && (
                <div style={{ padding: '10px 14px', background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.3)', borderRadius: 8, fontSize: 13, color: '#f87171', marginBottom: 14 }}>
                  ⚠️ {submitErr}
                </div>
              )}

              <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
                <button
                  id="btn-submit-allocate"
                  type="submit"
                  className="btn btn-primary"
                  disabled={submitting}
                  style={{ flex: 1, justifyContent: 'center' }}
                >
                  {submitting ? 'Allocating...' : '✅ Confirm Allocation'}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowModal(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
