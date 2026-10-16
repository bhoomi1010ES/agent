import React, { useEffect, useState } from 'react';
import { getJobArtifactContent } from '../../api/client';
import type { ArtifactDetailResponse } from '../../types/api';
import { ErrorAlert } from '../common/ErrorAlert';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { SeverityBadge } from '../common/SeverityBadge';
import { DiffViewer } from './DiffViewer';

interface ArtifactDetailViewProps {
  jobId: string;
  artifact: ArtifactDetailResponse;
}

export const ArtifactDetailView: React.FC<ArtifactDetailViewProps> = ({
  jobId,
  artifact,
}) => {
  const [content, setContent] = useState<unknown | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'structured' | 'raw'>('structured');
  const [copyFeedback, setCopyFeedback] = useState(false);

  useEffect(() => {
    let isMounted = true;
    const fetchContent = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await getJobArtifactContent(jobId, artifact.artifact_type, artifact.version);
        if (isMounted) setContent(data);
      } catch (err: unknown) {
        if (isMounted) {
          const msg = err instanceof Error ? err.message : 'Failed to fetch verified artifact content';
          setError(msg);
        }
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };

    fetchContent();
    return () => {
      isMounted = false;
    };
  }, [jobId, artifact.artifact_type, artifact.version]);

  const handleCopyHash = () => {
    navigator.clipboard.writeText(artifact.content_hash);
    setCopyFeedback(true);
    setTimeout(() => setCopyFeedback(false), 2000);
  };

  const parsed = typeof content === 'string' ? (() => {
    try { return JSON.parse(content); } catch { return content; }
  })() : content;

  const renderStructuredContent = () => {
    if (!parsed || typeof parsed !== 'object') {
      return (
        <pre style={{ background: '#f8fafc', padding: '1rem', borderRadius: 'var(--radius-md)', overflowX: 'auto', fontSize: '0.82rem' }}>
          {String(content || 'No content')}
        </pre>
      );
    }

    const data = parsed as Record<string, any>;

    // 1. RepoInventory
    if (artifact.artifact_type === 'RepoInventory' || data.languages || data.modules) {
      const languages = data.languages || {};
      const modules = Array.isArray(data.modules) ? data.modules : [];

      return (
        <div>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>
            Repository Language & Module Inventory
          </h4>

          {typeof languages === 'object' && Object.keys(languages).length > 0 && (
            <div style={{ marginBottom: '1.25rem' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                Languages Breakdown
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                {Object.entries(languages).map(([lang, count]) => (
                  <div
                    key={lang}
                    style={{
                      background: 'var(--bg-subtle)',
                      padding: '0.4rem 0.75rem',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.82rem',
                    }}
                  >
                    <strong>{lang}</strong>: {String(count)} LOC
                  </div>
                ))}
              </div>
            </div>
          )}

          {modules.length > 0 && (
            <div>
              <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                Discovered Modules ({modules.length})
              </div>
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Module Path</th>
                      <th>Lines of Code</th>
                      <th>Language</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modules.map((mod: any, idx: number) => (
                      <tr key={idx}>
                        <td><code>{mod.path || mod.name || String(mod)}</code></td>
                        <td>{mod.loc || mod.lines || '—'}</td>
                        <td>{mod.language || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      );
    }

    // 2. ChangeSet
    if (artifact.artifact_type === 'ChangeSet' || Array.isArray(data.files) || data.diff) {
      const files = Array.isArray(data.files) ? data.files : [];
      return (
        <div>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>
            Modernized Code Changes ({files.length} files)
          </h4>
          {files.map((file: any, idx: number) => (
            <div key={idx} style={{ marginBottom: '1rem' }}>
              <DiffViewer
                filename={file.path || file.filename || `File #${idx + 1}`}
                diffText={file.diff || file.patch || file.content || ''}
              />
            </div>
          ))}
          {data.diff && !files.length && (
            <DiffViewer diffText={data.diff} filename="Global Unified Patch" />
          )}
        </div>
      );
    }

    // 3. ReviewerFindings
    if (artifact.artifact_type === 'ReviewerFindings' || Array.isArray(data.findings)) {
      const findings = Array.isArray(data.findings) ? data.findings : [];
      return (
        <div>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>
            Automated & Reviewer Findings ({findings.length})
          </h4>
          {findings.length === 0 ? (
            <div className="alert alert-success">No critical architectural or security gaps detected!</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {findings.map((f: any, idx: number) => (
                <div
                  key={idx}
                  style={{
                    padding: '0.85rem',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-md)',
                    background: '#f8fafc',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <SeverityBadge severity={f.severity || 'medium'} />
                      <span style={{ fontWeight: 600, fontSize: '0.88rem' }}>{f.title || f.category || `Finding #${idx + 1}`}</span>
                    </div>
                    {f.file_path && <code style={{ fontSize: '0.75rem' }}>{f.file_path}:{f.line_number || 1}</code>}
                  </div>
                  <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
                    {f.description || f.message}
                  </p>
                  {f.remediation && (
                    <div style={{ fontSize: '0.78rem', color: '#15803d', background: '#ecfdf5', padding: '0.35rem 0.65rem', borderRadius: 'var(--radius-sm)' }}>
                      <strong>Remediation:</strong> {f.remediation}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    // 4. FeasibilityReport or ModernizationPlan (General Key-Value cards)
    return (
      <div>
        <h4 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '0.75rem' }}>
          {artifact.artifact_type} Summary
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
          {Object.entries(data).map(([key, val]) => {
            if (typeof val === 'object' && val !== null) return null;
            return (
              <div key={key} style={{ padding: '0.65rem 0.85rem', background: '#f8fafc', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'capitalize' }}>
                  {key.replace(/_/g, ' ')}
                </div>
                <div style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-primary)', marginTop: '0.15rem' }}>
                  {String(val)}
                </div>
              </div>
            );
          })}
        </div>
        <pre style={{ background: '#f8fafc', padding: '0.85rem', borderRadius: 'var(--radius-md)', overflowX: 'auto', fontSize: '0.82rem', border: '1px solid var(--border-subtle)' }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      </div>
    );
  };

  return (
    <div className="panel" style={{ marginTop: '1rem' }}>
      <div className="panel-header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <span style={{ fontWeight: 700, fontSize: '1.05rem' }}>{artifact.artifact_type}</span>
            <span className="brand-badge" style={{ background: '#4f46e5' }}>v{artifact.version}</span>
          </div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
            Storage: <code style={{ color: 'var(--text-secondary)' }}>{artifact.storage_ref}</code>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', background: 'var(--bg-subtle)', padding: '0.25rem 0.5rem', borderRadius: 'var(--radius-sm)', fontSize: '0.75rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>SHA-256:</span>
            <code style={{ fontFamily: 'var(--font-mono)' }}>{artifact.content_hash.slice(0, 16)}...</code>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ padding: '0.1rem 0.35rem', fontSize: '0.7rem' }}
              onClick={handleCopyHash}
              title="Copy full SHA-256 hash"
            >
              {copyFeedback ? '✓' : '📋'}
            </button>
          </div>
        </div>
      </div>

      <div className="tabs-nav">
        <button
          type="button"
          className={`tab-btn ${activeTab === 'structured' ? 'active' : ''}`}
          onClick={() => setActiveTab('structured')}
        >
          Structured Report
        </button>
        <button
          type="button"
          className={`tab-btn ${activeTab === 'raw' ? 'active' : ''}`}
          onClick={() => setActiveTab('raw')}
        >
          Raw JSON Content
        </button>
      </div>

      <div className="panel-body">
        {error && <ErrorAlert message={error} />}

        {isLoading ? (
          <LoadingSpinner label="Fetching verified artifact payload from object storage..." />
        ) : activeTab === 'structured' ? (
          renderStructuredContent()
        ) : (
          <div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.5rem' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => navigator.clipboard.writeText(JSON.stringify(parsed, null, 2))}
              >
                Copy Raw JSON
              </button>
            </div>
            <pre style={{ background: '#0f172a', color: '#f8fafc', padding: '1rem', borderRadius: 'var(--radius-md)', overflowX: 'auto', fontSize: '0.8rem', lineHeight: 1.5 }}>
              {JSON.stringify(parsed, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
};
