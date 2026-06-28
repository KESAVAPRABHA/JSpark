const BASE_URL = 'http://localhost:8000';

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'API error');
  }
  return res.json();
}

// Dashboard
export const getLeakage            = () => apiFetch('/api/dashboard/leakage');
export const getTeamHealth         = () => apiFetch('/api/dashboard/team-health');
export const getSupplyDemand       = () => apiFetch('/api/dashboard/supply-demand-forecast');
export const getAuditLog           = () => apiFetch('/api/dashboard/audit-log');
export const getSkillGaps          = () => apiFetch('/api/dashboard/skill-gaps');

// AI Recommend
export const postRecommend = (requirements, role) =>
  apiFetch('/api/recommend', {
    method: 'POST',
    body: JSON.stringify({ requirements, role }),
  });

// Risk Predict
export const postPredictRisk = (quality_status, csat_status, team_status) =>
  apiFetch('/api/predict-risk', {
    method: 'POST',
    body: JSON.stringify({ quality_status, csat_status, team_status }),
  });

// Allocations
export const getAllocations = () => apiFetch('/api/allocations');
export const getRiskScores  = () => apiFetch('/api/risk-scores');

export const postAllocate = (employee_id, project_id, percentage) =>
  apiFetch('/api/allocate', {
    method: 'POST',
    body: JSON.stringify({ employee_id, project_id, percentage }),
  });
