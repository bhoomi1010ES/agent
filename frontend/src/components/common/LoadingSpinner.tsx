import React from 'react';

interface LoadingSpinnerProps {
  label?: string;
}

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ label = 'Loading...' }) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '2rem 1rem', gap: '0.75rem' }}>
      <div className="loading-spinner" role="status" aria-label={label} />
      <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{label}</span>
    </div>
  );
};
