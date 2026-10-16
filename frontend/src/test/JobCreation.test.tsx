import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../api/client';
import { JobCreateModal } from '../components/jobs/JobCreateModal';

describe('JobCreateModal Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('validates required fields before submitting to API', async () => {
    const createSpy = vi.spyOn(api, 'createJob');

    render(
      <JobCreateModal
        isOpen={true}
        onClose={vi.fn()}
        onJobCreated={vi.fn()}
      />
    );

    // Clear repository input
    const repoInput = screen.getByLabelText(/Source Repository/i);
    fireEvent.change(repoInput, { target: { value: '' } });

    // Click submit
    const submitBtn = screen.getByText(/Create & Persist Job/i);
    fireEvent.click(submitBtn);

    // Expect inline validation error
    await waitFor(() => {
      expect(screen.getByText(/Source repository is required/i)).toBeInTheDocument();
    });

    // API should not be called
    expect(createSpy).not.toHaveBeenCalled();
  });

  it('submits valid intake form and notifies parent on success', async () => {
    const mockCreated = {
      job_id: '99999999-9999-9999-9999-999999999999',
      status: 'CREATED' as const,
      created_at: '2026-10-15T12:00:00Z',
    };
    const createSpy = vi.spyOn(api, 'createJob').mockResolvedValueOnce(mockCreated);
    const onJobCreated = vi.fn();
    const onClose = vi.fn();

    render(
      <JobCreateModal
        isOpen={true}
        onClose={onClose}
        onJobCreated={onJobCreated}
      />
    );

    const submitBtn = screen.getByText(/Create & Persist Job/i);
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          source_repository: 'https://github.com/legacy-org/monolith-core',
          source_revision: 'main',
          target_stack: expect.objectContaining({
            runtime: 'python3.12',
            framework: 'fastapi',
            architecture: 'modular-monolith',
          }),
          budget: expect.objectContaining({
            max_total_cost_usd: 500,
            max_duration_seconds: 7200,
          }),
        })
      );
      expect(onJobCreated).toHaveBeenCalledWith('99999999-9999-9999-9999-999999999999');
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('displays server validation or authorization error when API returns 422/403', async () => {
    vi.spyOn(api, 'createJob').mockRejectedValueOnce(
      new api.APIError(422, 'budget.max_total_cost_usd: value must be at least 1.0')
    );

    render(
      <JobCreateModal
        isOpen={true}
        onClose={vi.fn()}
        onJobCreated={vi.fn()}
      />
    );

    const submitBtn = screen.getByText(/Create & Persist Job/i);
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/budget.max_total_cost_usd: value must be at least 1.0/i)).toBeInTheDocument();
    });
  });
});
