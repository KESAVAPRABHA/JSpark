import React from 'react';

export default function KpiCard({ icon, label, value, sub, variant = 'violet' }) {
  return (
    <div className={`kpi-card ${variant}`}>
      <span className="kpi-icon">{icon}</span>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}
