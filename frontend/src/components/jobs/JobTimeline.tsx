import React from 'react';
import type { JobStatus } from '../../types/api';

interface JobTimelineProps {
  status: JobStatus;
}

export const JobTimeline: React.FC<JobTimelineProps> = ({ status }) => {
  const steps = [
    { key: 'CREATED', label: '1. Intake Created' },
    { key: 'IN_PROGRESS', label: '2. Analysis Active' },
    { key: 'AWAITING_HUMAN', label: '3. Gate Review' },
    { key: 'COMPLETED', label: '4. Finalized' },
  ];

  const getStepState = (stepKey: string) => {
    if (status === 'FAILED') {
      if (stepKey === 'COMPLETED') return 'failed';
    }
    if (status === 'CANCELLED') {
      if (stepKey === 'COMPLETED') return 'failed';
    }

    const order = ['CREATED', 'IN_PROGRESS', 'AWAITING_HUMAN', 'COMPLETED'];
    const currentIndex = order.indexOf(status === 'PAUSED' ? 'AWAITING_HUMAN' : status);
    const stepIndex = order.indexOf(stepKey);

    if (currentIndex > stepIndex) return 'completed';
    if (currentIndex === stepIndex) return 'active';
    return 'pending';
  };

  return (
    <div className="timeline" aria-label="Job Lifecycle Progression">
      {steps.map((step) => {
        const state = getStepState(step.key);
        return (
          <div key={step.key} className={`timeline-step ${state}`}>
            <div className="timeline-node">
              {state === 'completed' ? '✓' : state === 'failed' ? '✗' : '●'}
            </div>
            <div className="timeline-label">{step.label}</div>
          </div>
        );
      })}
    </div>
  );
};
