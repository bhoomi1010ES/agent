import React from 'react';

interface ErrorAlertProps {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export const ErrorAlert: React.FC<ErrorAlertProps> = ({ message, onRetry, onDismiss }) => {
  return (
    <div className="alert alert-danger" role="alert" style={{ justifyContent: 'space-between' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
        <span style={{ fontSize: '1.1rem', fontWeight: 'bold' }}>⚠️</span>
        <span>{message}</span>
      </div>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        {onRetry && (
          <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onDismiss}
            aria-label="Dismiss error"
            style={{ padding: '0.2rem 0.5rem' }}
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
};
