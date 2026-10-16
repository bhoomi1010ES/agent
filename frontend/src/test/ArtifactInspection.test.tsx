import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../api/client';
import { ArtifactDetailView } from '../components/artifacts/ArtifactDetailView';
import type { ArtifactDetailResponse } from '../types/api';

const mockArtifact: ArtifactDetailResponse = {
  artifact_id: 'art-1111',
  job_id: 'job-1111',
  artifact_type: 'RepoInventory',
  version: 1,
  content_hash: 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
  storage_ref: 's3://artifacts/job-1111/RepoInventory/v1.json',
  derived_from: [],
  artifact_metadata: {},
  created_at: '2026-10-15T10:00:00Z',
};

describe('Artifact Inspection Components', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders RepoInventory structured view with languages and module inventory', async () => {
    const payload = {
      languages: { Python: 12500, JavaScript: 4300 },
      modules: [
        { path: 'src/core/parser.py', loc: 450, language: 'Python' },
        { path: 'src/utils/helpers.js', loc: 120, language: 'JavaScript' },
      ],
    };
    vi.spyOn(api, 'getJobArtifactContent').mockResolvedValueOnce(payload);

    render(<ArtifactDetailView jobId="job-1111" artifact={mockArtifact} />);

    await waitFor(() => {
      expect(screen.getByText(/Repository Language & Module Inventory/i)).toBeInTheDocument();
      expect(screen.getAllByText('Python').length).toBeGreaterThan(0);
      expect(screen.getByText('src/core/parser.py')).toBeInTheDocument();
      expect(screen.getByText('450')).toBeInTheDocument();
    });
  });

  it('renders ReviewerFindings with severity tags and remediation notes', async () => {
    const findingsArtifact: ArtifactDetailResponse = {
      ...mockArtifact,
      artifact_type: 'ReviewerFindings',
    };
    const payload = {
      findings: [
        {
          id: 'F-1',
          severity: 'CRITICAL',
          title: 'Hardcoded Database Password',
          description: 'Plaintext password detected in legacy config.py',
          remediation: 'Migrate to environment secret injector',
          file_path: 'legacy/config.py',
          line_number: 14,
        },
      ],
    };
    vi.spyOn(api, 'getJobArtifactContent').mockResolvedValueOnce(payload);

    render(<ArtifactDetailView jobId="job-1111" artifact={findingsArtifact} />);

    await waitFor(() => {
      expect(screen.getByText('Hardcoded Database Password')).toBeInTheDocument();
      expect(screen.getByText('CRITICAL')).toBeInTheDocument();
      expect(screen.getByText(/Migrate to environment secret injector/i)).toBeInTheDocument();
    });
  });

  it('toggles between structured view and raw JSON content', async () => {
    const reportArtifact: ArtifactDetailResponse = {
      ...mockArtifact,
      artifact_type: 'FeasibilityReport',
    };
    const payload = { status: 'analyzed', total_files: 42 };
    vi.spyOn(api, 'getJobArtifactContent').mockResolvedValueOnce(payload);

    render(<ArtifactDetailView jobId="job-1111" artifact={reportArtifact} />);

    await waitFor(() => {
      expect(screen.getByText(/FeasibilityReport Summary/i)).toBeInTheDocument();
    });

    // Click Raw JSON tab
    const rawTab = screen.getByText('Raw JSON Content');
    fireEvent.click(rawTab);

    expect(screen.getByText('Copy Raw JSON')).toBeInTheDocument();
    expect(screen.getByText(/"total_files": 42/i)).toBeInTheDocument();
  });
});
