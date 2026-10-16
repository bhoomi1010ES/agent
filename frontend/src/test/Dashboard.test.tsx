import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../api/client';
import { DashboardView } from '../components/dashboard/DashboardView';
import type { JobListResponse } from '../types/api';

const mockJobList: JobListResponse = {
  items: [
    {
      job_id: '11111111-1111-1111-1111-111111111111',
      tenant_id: 'tenant-1',
      owner_user_id: 'user-1',
      status: 'AWAITING_HUMAN',
      source_ref: 'https://github.com/org/legacy-repo@main',
      target_stack_spec: { runtime: 'python3.12', framework: 'fastapi', architecture: 'modular-monolith' },
      budget: { max_total_cost_usd: 500, max_duration_seconds: 7200 },
      created_at: '2026-10-15T10:00:00Z',
      updated_at: '2026-10-15T10:05:00Z',
      finished_at: null,
    },
    {
      job_id: '22222222-2222-2222-2222-222222222222',
      tenant_id: 'tenant-1',
      owner_user_id: 'user-1',
      status: 'COMPLETED',
      source_ref: 'https://github.com/org/payment-service@v2.0',
      target_stack_spec: { runtime: 'node20', framework: 'express', architecture: 'microservices' },
      budget: { max_total_cost_usd: 300, max_duration_seconds: 3600 },
      created_at: '2026-10-15T09:00:00Z',
      updated_at: '2026-10-15T09:45:00Z',
      finished_at: '2026-10-15T09:45:00Z',
    },
  ],
  pagination: { offset: 0, limit: 25, total: 2 },
};

describe('DashboardView Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders dashboard metrics and job table from API data', async () => {
    vi.spyOn(api, 'listJobs').mockResolvedValueOnce(mockJobList);

    const onSelectJob = vi.fn();
    const onCreateJob = vi.fn();

    render(
      <DashboardView
        onSelectJob={onSelectJob}
        onCreateJob={onCreateJob}
        refreshTrigger={0}
      />
    );

    // Initial loading indicator
    expect(screen.getByText(/Fetching jobs from control plane/i)).toBeInTheDocument();

    // Table rows appear
    await waitFor(() => {
      expect(screen.getByText('https://github.com/org/legacy-repo')).toBeInTheDocument();
      expect(screen.getByText('https://github.com/org/payment-service')).toBeInTheDocument();
    });

    // Check status badges
    expect(screen.getByText('AWAITING HUMAN')).toBeInTheDocument();
    expect(screen.getAllByText('COMPLETED').length).toBeGreaterThan(0);

    // Check metric counts
    expect(screen.getByText('Total Jobs')).toBeInTheDocument();
  });

  it('filters jobs via client search input', async () => {
    vi.spyOn(api, 'listJobs').mockResolvedValueOnce(mockJobList);

    render(
      <DashboardView
        onSelectJob={vi.fn()}
        onCreateJob={vi.fn()}
        refreshTrigger={0}
      />
    );

    await waitFor(() => {
      expect(screen.getByText('https://github.com/org/legacy-repo')).toBeInTheDocument();
    });

    const searchInput = screen.getByLabelText(/Search jobs/i);
    fireEvent.change(searchInput, { target: { value: 'payment' } });

    // legacy-repo should be filtered out, payment-service remains
    expect(screen.queryByText('https://github.com/org/legacy-repo')).not.toBeInTheDocument();
    expect(screen.getByText('https://github.com/org/payment-service')).toBeInTheDocument();
  });

  it('displays error recovery alert and allows retry when API fails', async () => {
    const listSpy = vi.spyOn(api, 'listJobs').mockRejectedValueOnce(new Error('Network error: server unreachable'));

    render(
      <DashboardView
        onSelectJob={vi.fn()}
        onCreateJob={vi.fn()}
        refreshTrigger={0}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/Network error: server unreachable/i)).toBeInTheDocument();
    });

    // Click retry
    listSpy.mockResolvedValueOnce(mockJobList);
    const retryBtn = screen.getByText('Retry');
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText('https://github.com/org/legacy-repo')).toBeInTheDocument();
    });
  });
});
