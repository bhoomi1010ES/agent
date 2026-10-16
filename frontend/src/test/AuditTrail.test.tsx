import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../api/client';
import { AuditTrailView } from '../components/audit/AuditTrailView';

describe('AuditTrailView Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders chronological audit events and expands payload details', async () => {
    vi.spyOn(api, 'listJobAuditEvents').mockResolvedValueOnce({
      items: [
        {
          event_id: 'ev-1',
          job_id: 'job-1',
          actor: 'user-lead',
          actor_user_id: '11111111-1111-1111-1111-111111111111',
          action: 'JOB_CREATED',
          correlation_id: 'corr-12345',
          payload: { repo: 'legacy-core', revision: 'main' },
          event_time: '2026-10-15T10:00:00Z',
          event_version: 1,
        },
      ],
      pagination: { offset: 0, limit: 100, total: 1 },
    });

    render(<AuditTrailView jobId="job-1" />);

    await waitFor(() => {
      expect(screen.getByText('JOB_CREATED')).toBeInTheDocument();
      expect(screen.getByText('user-lead')).toBeInTheDocument();
      expect(screen.getByText('corr-12345')).toBeInTheDocument();
    });

    // Expand payload
    const viewPayloadBtn = screen.getByText(/View Payload/i);
    fireEvent.click(viewPayloadBtn);

    expect(screen.getByText(/"repo": "legacy-core"/i)).toBeInTheDocument();
  });

  it('gracefully handles 403 Forbidden with security explanation and role guidance', async () => {
    vi.spyOn(api, 'listJobAuditEvents').mockRejectedValueOnce(
      new api.APIError(403, 'Forbidden: audit.view required')
    );

    render(<AuditTrailView jobId="job-1" />);

    await waitFor(() => {
      expect(screen.getByText(/Restricted Audit Trail Access/i)).toBeInTheDocument();
      expect(screen.getByText('audit.view')).toBeInTheDocument();
    });
  });
});
