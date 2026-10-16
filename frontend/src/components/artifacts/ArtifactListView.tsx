import React, { useEffect, useState } from 'react';
import { listJobArtifacts } from '../../api/client';
import type { ArtifactDetailResponse } from '../../types/api';
import { ErrorAlert } from '../common/ErrorAlert';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { ArtifactDetailView } from './ArtifactDetailView';

interface ArtifactListViewProps {
  jobId: string;
}

export const ArtifactListView: React.FC<ArtifactListViewProps> = ({ jobId }) => {
  const [artifacts, setArtifacts] = useState<ArtifactDetailResponse[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchArtifacts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listJobArtifacts(jobId);
      const items = response.items || [];
      setArtifacts(items);
      if (items.length > 0 && !selectedArtifact) {
        setSelectedArtifact(items[0]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch job artifacts';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchArtifacts();
  }, [jobId]);

  return (
    <div>
      {error && <ErrorAlert message={error} onRetry={fetchArtifacts} />}

      {isLoading ? (
        <LoadingSpinner label="Fetching registered modernization artifacts..." />
      ) : artifacts.length === 0 ? (
        <div className="empty-state">
          <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>📦</div>
          <div className="empty-state-title">No Artifacts Generated Yet</div>
          <p style={{ maxWidth: '420px', margin: '0 auto', fontSize: '0.85rem' }}>
            Analysis or modernization artifacts (RepoInventory, FeasibilityReport, ChangeSet, etc.) will appear here once generated and validated by platform agents.
          </p>
        </div>
      ) : (
        <div>
          {/* Artifact selector pills */}
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
            {artifacts.map((art) => {
              const isSelected = selectedArtifact?.artifact_id === art.artifact_id;
              return (
                <button
                  key={art.artifact_id}
                  type="button"
                  className={`btn ${isSelected ? 'btn-primary' : 'btn-secondary'} btn-sm`}
                  onClick={() => setSelectedArtifact(art)}
                  style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}
                >
                  <span>{art.artifact_type}</span>
                  <span
                    style={{
                      background: isSelected ? 'rgba(255,255,255,0.25)' : 'var(--bg-muted)',
                      padding: '0.1rem 0.35rem',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.72rem',
                    }}
                  >
                    v{art.version}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Active Artifact Detailed Inspector */}
          {selectedArtifact && (
            <ArtifactDetailView jobId={jobId} artifact={selectedArtifact} />
          )}
        </div>
      )}
    </div>
  );
};
