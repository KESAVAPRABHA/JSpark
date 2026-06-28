import React from 'react';

export default function LoadingSpinner({ text = 'Loading data...' }) {
  return (
    <div className="spinner-container">
      <div className="spinner" />
      <span>{text}</span>
    </div>
  );
}
