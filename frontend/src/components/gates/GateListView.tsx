import React, { useEffect, useState } from 'react';
import { listJobGates } from '../../api/client';
import type { GateDetailResponse } from '../../types/api';
import { ErrorAlert } from '../common/ErrorAlert';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { StatusBadge } from '../common/StatusBadge';
import { GateDecisionModal } from './GateDecisionModal';

interface GateListViewProps {
  jobId: string;
}

export const GateListView: React.FC<GateListViewProps> = ({ jobId }) => {
  const [gates, setGates] = useState<GateDetailResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedGate, setSelectedGate] = useState<GateDetailResponse | null>(null);

  const fetchGates = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listJobGates(jobId);
      setGates(response.items || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch gates for job';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchGates();
  }, [jobId]);

  const formatDate = (isoString: string) => {
    try {
      return new Date(isoString).toLocaleString();
    } catch {
      return isoString;
    }
  };

  return (
    <div>
      {error && <ErrorAlert message={error} onRetry={fetchGates} />}

      {isLoading ? (
        <LoadingSpinner label="Fetching human approval gates..." />
      ) : gates.length === 0 ? (
        <div className="empty-state">
          <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>🛡️</div>
          <div className="empty-state-title">No Approval Gates Configured</div>
          <p style={{ maxWidth: '420px', margin: '0 auto', fontSize: '0.85rem' }}>
            This modernization job has not paused at any human-in-the-loop gates (G1 Feasibility, G2 Characterization, G3 Blueprint, or G4 Delivery).
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {gates.map((gate) => (
            <div
              key={gate.gate_id}
              className="panel"
              style={{
                marginBottom: 0,
                borderLeft: `4px solid ${
                  gate.state === 'pending'
                    ? 'var(--warning-icon)'
                    : gate.state === 'approved'
                    ? 'var(--success-icon)'
                    : 'var(--danger-icon)'
                }`,
              }}
            >
              <div className="panel-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <span style={{ fontWeight: 700, fontSize: '1.05rem' }}>{gate.gate_type}</span>
                  <StatusBadge status={gate.state} />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                  <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                    Budget Used: <strong>${(gate.budget_used_cents / 100).toFixed(2)}</strong>
                  </span>
                  {gate.state === 'pending' && (
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={() => setSelectedGate(gate)}
                    >
                      Review Gate Decision →
                    </button>
                  )}
                </div>
              </div>

              <div className="panel-body">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '1rem', fontSize: '0.85rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Gate ID:</span>{' '}
                    <code className="code-snippet">{gate.gate_id}</code>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Requested:</span>{' '}
                    <span>{formatDate(gate.requested_at)}</span>
                  </div>
                  {gate.resolved_at && (
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Resolved:</span>{' '}
                      <span>{formatDate(gate.resolved_at)}</span>
                    </div>
                  )}
                </div>

                {gate.needs_human_flags.length > 0 && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                      Automated Review Flags ({gate.needs_human_flags.length}):
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                      {gate.needs_human_flags.map((flag, idx) => (
                        <div
                          key={idx}
                          style={{
                            padding: '0.35rem 0.65rem',
                            backgroundColor: '#fef3c7',
                            border: '1px solid #fde68a',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.78rem',
                            color: '#92400e',
                          }}
                        >
                          <strong>{flag.code || 'FLAG'}</strong>: {flag.message || JSON.stringify(flag.details || {})}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedGate && (
        <GateDecisionModal
          isOpen={true}
          onClose={() => setSelectedGate(null)}
          jobId={jobId}
          gate={selectedGate}
          onDecisionRecorded={() => {
            setSelectedGate(null);
            fetchGates();
          }}
          onConflict={() => {
            setSelectedGate(null);
            fetchGates();
          }}
        />
      )}
    </div>
  );
};
