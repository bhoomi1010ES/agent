import React, { useEffect, useState } from 'react';
import { getJob } from '../../api/client';
import type { JobDetailResponse } from '../../types/api';
import { ArtifactListView } from '../artifacts/ArtifactListView';
import { AuditTrailView } from '../audit/AuditTrailView';
import { ErrorAlert } from '../common/ErrorAlert';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { StatusBadge } from '../common/StatusBadge';
import { GateListView } from '../gates/GateListView';
import { JobTimeline } from './JobTimeline';

interface JobDetailViewProps {
  jobId: string;
  onBack: () => void;
}

export const JobDetailView: React.FC<JobDetailViewProps> = ({ jobId, onBack }) => {
  const [job, setJob] = useState<JobDetailResponse | null>(null);
  const [activeTab, setActiveTab] = useState<'gates' | 'artifacts' | 'audit'>('gates');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pollingEnabled, setPollingEnabled] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());

  const fetchJob = async (isBackgroundPoll = false) => {
    if (!isBackgroundPoll) setIsLoading(true);
    setError(null);
    try {
      const data = await getJob(jobId);
      setJob(data);
      setLastRefreshed(new Date());

      // Auto-disable polling if reached terminal state
      if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(data.status)) {
        setPollingEnabled(false);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch job details';
      setError(msg);
    } finally {
      if (!isBackgroundPoll) setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchJob();
  }, [jobId]);

  // Bounded Polling Effect with cleanup
  useEffect(() => {
    if (!pollingEnabled) return;

    const intervalId = setInterval(() => {
      fetchJob(true);
    }, 5000);

    return () => {
      clearInterval(intervalId);
    };
  }, [pollingEnabled, jobId]);

  const formatDate = (isoString?: string | null) => {
    if (!isoString) return '—';
    try {
      return new Date(isoString).toLocaleString();
    } catch {
      return isoString;
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <div>
      {/* Breadcrumb / Back button */}
      <div style={{ marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={onBack}
          style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}
        >
          ← Back to All Jobs
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.82rem', cursor: 'pointer', color: 'var(--text-secondary)' }}>
            <input
              type="checkbox"
              checked={pollingEnabled}
              onChange={(e) => setPollingEnabled(e.target.checked)}
              disabled={job ? ['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status) : false}
            />
            <span>Bounded Polling (5s)</span>
            {pollingEnabled && <span className="loading-spinner" style={{ width: '0.85rem', height: '0.85rem', borderWidth: '1.5px' }} />}
          </label>

          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Refreshed: {lastRefreshed.toLocaleTimeString()}
          </span>

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => fetchJob(false)}
            disabled={isLoading}
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {error && <ErrorAlert message={error} onRetry={() => fetchJob(false)} />}

      {isLoading && !job ? (
        <LoadingSpinner label="Fetching job details from platform..." />
      ) : !job ? (
        <div className="empty-state">
          <div className="empty-state-title">Job Not Found</div>
          <p>The requested modernization job was not found in your authorized tenant scope.</p>
        </div>
      ) : (
        <div>
          {/* Main Job Banner */}
          <div className="panel">
            <div className="panel-header" style={{ padding: '1.25rem 1.5rem' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                  <h1 style={{ fontSize: '1.35rem', fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
                    {job.source_ref.split('@')[0]}
                  </h1>
                  <span className="code-snippet">rev: {job.source_ref.split('@')[1] || 'main'}</span>
                  <StatusBadge status={job.status} />
                </div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '0.35rem', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                  <span>
                    Job UUID: <code style={{ color: 'var(--text-primary)' }}>{job.job_id}</code>{' '}
                    <button
                      type="button"
                      style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.75rem' }}
                      onClick={() => handleCopy(job.job_id)}
                      title="Copy Job UUID"
                    >
                      📋
                    </button>
                  </span>
                  <span>Created: {formatDate(job.created_at)}</span>
                  <span>Updated: {formatDate(job.updated_at)}</span>
                  {job.finished_at && <span>Finished: {formatDate(job.finished_at)}</span>}
                </div>
              </div>
            </div>

            <div className="panel-body">
              {/* Modernization Transformation Vector */}
              <div className="transform-vector" style={{ margin: '0 0 1.5rem 0' }}>
                <span className="stack-pill legacy">
                  {job.target_stack_spec?.legacy_source || 'Legacy Monolithic Source'}
                </span>
                <span className="vector-arrow">➔ ➔ ➔</span>
                <span className="stack-pill modern">
                  Target: {job.target_stack_spec?.runtime} ({job.target_stack_spec?.framework}) • {job.target_stack_spec?.architecture || 'modular'}
                </span>
              </div>

              {/* Timeline progression */}
              <JobTimeline status={job.status} />

              {/* Swarm Status Ribbon */}
              <div style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '0.75rem 1rem', marginTop: '1.25rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', color: '#a5b4fc', fontWeight: 600 }}>
                  <span className="radar-dot"></span>
                  <span>Swarm Pipeline Telemetry:</span>
                  <span style={{ color: '#ffffff', fontWeight: 400 }}>Orchestrating AST Analysis & Code Generation</span>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <span className="swarm-agent-pill active">Tree-Sitter AST</span>
                  <span className="swarm-agent-pill active">Complexity Scanner</span>
                  <span className="swarm-agent-pill active">Diff Synthesizer</span>
                </div>
              </div>

              {/* Configuration Specifications */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', marginTop: '1.5rem', paddingTop: '1.25rem', borderTop: '1px solid var(--border-light)' }}>
                <div>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    Target Technology Stack
                  </div>
                  <div style={{ fontSize: '0.92rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.2rem' }}>
                    {job.target_stack_spec?.runtime} / {job.target_stack_spec?.framework}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Arch: {job.target_stack_spec?.architecture}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    Guardrail Budget
                  </div>
                  <div style={{ fontSize: '0.92rem', fontWeight: 600, color: 'var(--text-primary)', marginTop: '0.2rem' }}>
                    Max Cost: ${Number(job.budget?.max_total_cost_usd || 0).toFixed(2)}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Max Duration: {Math.round((job.budget?.max_duration_seconds || 0) / 60)} minutes
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                    Tenant Scope & Identity
                  </div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                    Tenant: <code>{job.tenant_id.slice(0, 8)}...</code>
                  </div>
                  <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                    Owner: <code>{job.owner_user_id.slice(0, 8)}...</code>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Sub-view Navigation Tabs */}
          <div className="panel">
            <div className="tabs-nav" style={{ padding: '0.25rem 1.25rem 0' }}>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'gates' ? 'active' : ''}`}
                onClick={() => setActiveTab('gates')}
              >
                🛡️ Human Approval Gates
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'artifacts' ? 'active' : ''}`}
                onClick={() => setActiveTab('artifacts')}
              >
                📦 Modernization Artifacts
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'audit' ? 'active' : ''}`}
                onClick={() => setActiveTab('audit')}
              >
                📜 Compliance Audit Trail
              </button>
            </div>

            <div className="panel-body">
              {activeTab === 'gates' && <GateListView jobId={jobId} />}
              {activeTab === 'artifacts' && <ArtifactListView jobId={jobId} />}
              {activeTab === 'audit' && <AuditTrailView jobId={jobId} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
