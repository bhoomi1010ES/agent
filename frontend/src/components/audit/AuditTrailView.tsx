import React, { useEffect, useState } from 'react';
import { APIError, listJobAuditEvents } from '../../api/client';
import type { AuditEventResponse } from '../../types/api';
import { ErrorAlert } from '../common/ErrorAlert';
import { LoadingSpinner } from '../common/LoadingSpinner';

interface AuditTrailViewProps {
  jobId: string;
}

export const AuditTrailView: React.FC<AuditTrailViewProps> = ({ jobId }) => {
  const [events, setEvents] = useState<AuditEventResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isForbidden, setIsForbidden] = useState(false);
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);

  const fetchAuditEvents = async () => {
    setIsLoading(true);
    setError(null);
    setIsForbidden(false);
    try {
      const response = await listJobAuditEvents(jobId, { limit: 100 });
      setEvents(response.items || []);
    } catch (err: unknown) {
      if (err instanceof APIError && (err.status === 403 || err.status === 401)) {
        setIsForbidden(true);
      } else {
        const msg = err instanceof Error ? err.message : 'Failed to fetch audit events';
        setError(msg);
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAuditEvents();
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
      {error && <ErrorAlert message={error} onRetry={fetchAuditEvents} />}

      {isForbidden ? (
        <div className="alert alert-warning" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '0.5rem' }}>
          <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>🔒 Restricted Audit Trail Access</div>
          <p style={{ fontSize: '0.85rem' }}>
            Viewing chronological platform audit events requires explicit <code>audit.view</code> authorization granted to <strong>Owner</strong> and <strong>Admin</strong> roles. Reviewer and Approver roles are restricted from inspecting raw governance trails.
          </p>
          <div style={{ fontSize: '0.8rem', color: '#92400e' }}>
            Tip: You can switch to the <em>Owner</em> or <em>Admin</em> role in the top black <strong>Auth & Role Settings</strong> bar to inspect audit compliance logs.
          </div>
        </div>
      ) : isLoading ? (
        <LoadingSpinner label="Loading immutable audit trail from platform..." />
      ) : events.length === 0 ? (
        <div className="empty-state">
          <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📜</div>
          <div className="empty-state-title">No Audit Events Logged</div>
          <p style={{ maxWidth: '420px', margin: '0 auto', fontSize: '0.85rem' }}>
            Platform lifecycle mutations, gate decisions, and artifact deliveries will be recorded chronologically here.
          </p>
        </div>
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Correlation ID</th>
                <th style={{ textAlign: 'right' }}>Payload Details</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => {
                const isExpanded = expandedEventId === ev.event_id;
                return (
                  <React.Fragment key={ev.event_id}>
                    <tr>
                      <td style={{ fontSize: '0.82rem', whiteSpace: 'nowrap' }}>
                        {formatDate(ev.event_time)}
                      </td>
                      <td>
                        <span
                          style={{
                            fontWeight: 700,
                            fontSize: '0.8rem',
                            color: ev.action.includes('REJECT')
                              ? '#dc2626'
                              : ev.action.includes('APPROVE')
                              ? '#15803d'
                              : 'var(--primary-700)',
                            background: 'var(--bg-subtle)',
                            padding: '0.2rem 0.5rem',
                            borderRadius: 'var(--radius-sm)',
                          }}
                        >
                          {ev.action}
                        </span>
                      </td>
                      <td>
                        <code style={{ fontSize: '0.78rem' }}>{ev.actor}</code>
                      </td>
                      <td>
                        {ev.correlation_id ? (
                          <code style={{ fontSize: '0.75rem' }}>{ev.correlation_id}</code>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>—</span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {ev.payload && Object.keys(ev.payload).length > 0 && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}
                            onClick={() => setExpandedEventId(isExpanded ? null : ev.event_id)}
                          >
                            {isExpanded ? 'Hide Payload ▲' : 'View Payload ▼'}
                          </button>
                        )}
                      </td>
                    </tr>
                    {isExpanded && ev.payload && (
                      <tr>
                        <td colSpan={5} style={{ background: '#f8fafc', padding: '0.75rem 1.25rem' }}>
                          <pre style={{ margin: 0, fontSize: '0.78rem', background: '#0f172a', color: '#f8fafc', padding: '0.75rem', borderRadius: 'var(--radius-sm)', overflowX: 'auto' }}>
                            {JSON.stringify(ev.payload, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
