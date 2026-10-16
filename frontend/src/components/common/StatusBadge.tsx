import React from 'react';
import type { JobStatus } from '../../types/api';

interface StatusBadgeProps {
  status: JobStatus | string;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, className = '' }) => {
  return (
    <span className={`status-badge ${status} ${className}`}>
      <span
        style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          backgroundColor: 'currentColor',
          display: 'inline-block',
        }}
      />
      {status.replace(/_/g, ' ')}
    </span>
  );
};
