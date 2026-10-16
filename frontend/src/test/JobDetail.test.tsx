import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../api/client';
import { JobDetailView } from '../components/jobs/JobDetailView';
import type { JobDetailResponse } from '../types/api';

const mockJobDetail: JobDetailResponse = {
  job_id: 'job-1234-5678-90ab',
  tenant_id: 'tenant-1234',
  owner_user_id: 'owner-5678',
  status: 'IN_PROGRESS',
  source_ref: 'https://github.com/corp/core-service@release-v1',
  target_stack_spec: { runtime: 'python3.12', framework: 'fastapi', architecture: 'clean-architecture' },
  budget: { max_total_cost_usd: 750, max_duration_seconds: 10800 },
  created_at: '2026-10-15T08:00:00Z',
  updated_at: '2026-10-15T08:30:00Z',
  finished_at: null,
};

describe('JobDetailView Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders job metadata, configuration, and lifecycle progress timeline', async () => {
    vi.spyOn(api, 'getJob').mockResolvedValueOnce(mockJobDetail);
    vi.spyOn(api, 'listJobGates').mockResolvedValueOnce({ items: [], total: 0 });

    const onBack = vi.fn();
    render(<JobDetailView jobId="job-1234-5678-90ab" onBack={onBack} />);

    // Shows loading then job banner
    await waitFor(() => {
      expect(screen.getByText('https://github.com/corp/core-service')).toBeInTheDocument();
      expect(screen.getByText('rev: release-v1')).toBeInTheDocument();
    });

    // Check status badge
    expect(screen.getByText('IN PROGRESS')).toBeInTheDocument();

    // Check Target Stack specifications
    expect(screen.getByText(/python3.12 \/ fastapi/i)).toBeInTheDocument();
    expect(screen.getByText(/Max Cost: \$750.00/i)).toBeInTheDocument();
    expect(screen.getByText(/Max Duration: 180 minutes/i)).toBeInTheDocument();

    // Check timeline stages
    expect(screen.getByText('1. Intake Created')).toBeInTheDocument();
    expect(screen.getByText('2. Analysis Active')).toBeInTheDocument();
    expect(screen.getByText('3. Gate Review')).toBeInTheDocument();

    // Check tab navigation exists
    expect(screen.getByRole('button', { name: /Human Approval Gates/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Modernization Artifacts/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Compliance Audit Trail/i })).toBeInTheDocument();

    // Back button triggers callback
    const backBtn = screen.getByText(/Back to All Jobs/i);
    fireEvent.click(backBtn);
    expect(onBack).toHaveBeenCalled();
  });

  it('allows switching to Artifacts and Audit Trail tabs', async () => {
    vi.spyOn(api, 'getJob').mockResolvedValueOnce(mockJobDetail);
    vi.spyOn(api, 'listJobGates').mockResolvedValueOnce({ items: [], total: 0 });
    vi.spyOn(api, 'listJobArtifacts').mockResolvedValueOnce({ items: [], total: 0 });

    render(<JobDetailView jobId="job-1234-5678-90ab" onBack={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('https://github.com/corp/core-service')).toBeInTheDocument();
    });

    // Switch to Artifacts Tab
    const artifactsTab = screen.getByText(/Modernization Artifacts/i);
    fireEvent.click(artifactsTab);

    await waitFor(() => {
      expect(screen.getByText(/No Artifacts Generated Yet/i)).toBeInTheDocument();
    });
  });

  it('toggles bounded polling interval without errors', async () => {
    vi.spyOn(api, 'getJob').mockResolvedValue(mockJobDetail);
    vi.spyOn(api, 'listJobGates').mockResolvedValue({ items: [], total: 0 });

    render(<JobDetailView jobId="job-1234-5678-90ab" onBack={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('https://github.com/corp/core-service')).toBeInTheDocument();
    });

    const pollCheckbox = screen.getByLabelText(/Bounded Polling/i);
    expect(pollCheckbox).not.toBeChecked();

    fireEvent.click(pollCheckbox);
    expect(pollCheckbox).toBeChecked();

    fireEvent.click(pollCheckbox);
    expect(pollCheckbox).not.toBeChecked();
  });
});
