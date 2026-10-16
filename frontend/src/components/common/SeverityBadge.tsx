import React from 'react';

interface SeverityBadgeProps {
  severity: string;
}

export const SeverityBadge: React.FC<SeverityBadgeProps> = ({ severity }) => {
  const norm = (severity || 'medium').toLowerCase();
  return <span className={`severity-badge severity-${norm}`}>{severity}</span>;
};
