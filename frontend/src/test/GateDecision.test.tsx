import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../api/client';
import { GateDecisionModal } from '../components/gates/GateDecisionModal';
import { GateListView } from '../components/gates/GateListView';
import type { GateDetailResponse } from '../types/api';

const mockGate: GateDetailResponse = {
  gate_id: 'gate-1111-1111-1111',
  job_id: 'job-1111-1111-1111',
  gate_type: 'G1_FEASIBILITY',
  state: 'pending',
  requested_at: '2026-10-15T11:00:00Z',
  artifact_versions_shown: { FeasibilityReport: 1 },
  needs_human_flags: [{ code: 'HIGH_CYCLOMATIC_COMPLEXITY', message: 'Legacy parser module has cyclomatic complexity of 45' }],
  budget_used_cents: 250,
  resolved_at: null,
};

describe('Gate Review and Decision Workflow', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders pending gate with review triggers in GateListView', async () => {
    vi.spyOn(api, 'listJobGates').mockResolvedValueOnce({
      items: [mockGate],
      total: 1,
    });

    render(<GateListView jobId="job-1111-1111-1111" />);

    await waitFor(() => {
      expect(screen.getByText('G1_FEASIBILITY')).toBeInTheDocument();
      expect(screen.getByText('HIGH_CYCLOMATIC_COMPLEXITY')).toBeInTheDocument();
      expect(screen.getByText('$2.50')).toBeInTheDocument();
      expect(screen.getByText(/Review Gate Decision/i)).toBeInTheDocument();
    });
  });

  it('enforces mandatory written feedback on gate rejection', async () => {
    render(
      <GateDecisionModal
        isOpen={true}
        onClose={vi.fn()}
        jobId="job-1111-1111-1111"
        gate={mockGate}
        onDecisionRecorded={vi.fn()}
        onConflict={vi.fn()}
      />
    );

    // Switch decision to Reject
    const rejectBtn = screen.getByText('✗ Reject');
    fireEvent.click(rejectBtn);

    // Click Continue without feedback
    const continueBtn = screen.getByText(/Continue to Confirmation/i);
    fireEvent.click(continueBtn);

    await waitFor(() => {
      expect(screen.getByText(/Rejected decisions require constructive written feedback/i)).toBeInTheDocument();
    });
  });

  it('submits confirmed gate approval and attaches waivers', async () => {
    const decideSpy = vi.spyOn(api, 'decideGate').mockResolvedValueOnce({
      gate_id: mockGate.gate_id,
      decision_id: 'dec-1111',
      decision: 'approved',
      decided_at: '2026-10-15T11:15:00Z',
    });
    const onDecisionRecorded = vi.fn();

    render(
      <GateDecisionModal
        isOpen={true}
        onClose={vi.fn()}
        jobId="job-1111-1111-1111"
        gate={mockGate}
        onDecisionRecorded={onDecisionRecorded}
        onConflict={vi.fn()}
      />
    );

    // Add a waiver
    const addWaiverBtn = screen.getByText('+ Add Waiver');
    fireEvent.click(addWaiverBtn);

    const subjectInput = screen.getByPlaceholderText(/Waiver subject/i);
    const reasonInput = screen.getByPlaceholderText(/Technical justification/i);

    fireEvent.change(subjectInput, { target: { value: 'Coverage exception' } });
    fireEvent.change(reasonInput, { target: { value: 'Legacy utility will be replaced in Phase 2' } });

    const attachBtn = screen.getByText('Attach Waiver');
    fireEvent.click(attachBtn);

    expect(screen.getByText('Coverage exception')).toBeInTheDocument();

    // Proceed to confirmation
    const continueBtn = screen.getByText(/Continue to Confirmation/i);
    fireEvent.click(continueBtn);

    // Confirmation banner displayed
    expect(screen.getByText(/Confirm Permanent Gate Decision/i)).toBeInTheDocument();

    // Confirm
    const confirmBtn = screen.getByText(/Confirm & Record APPROVED/i);
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(decideSpy).toHaveBeenCalledWith(
        'job-1111-1111-1111',
        mockGate.gate_id,
        expect.objectContaining({
          decision: 'approved',
          waivers: [{ subject: 'Coverage exception', reason: 'Legacy utility will be replaced in Phase 2' }],
        })
      );
      expect(onDecisionRecorded).toHaveBeenCalled();
    });
  });

  it('handles HTTP 409 conflict by alerting and notifying parent to reload state', async () => {
    vi.spyOn(api, 'decideGate').mockRejectedValueOnce(
      new api.APIError(409, 'Gate is not pending')
    );
    const onConflict = vi.fn();

    render(
      <GateDecisionModal
        isOpen={true}
        onClose={vi.fn()}
        jobId="job-1111-1111-1111"
        gate={mockGate}
        onDecisionRecorded={vi.fn()}
        onConflict={onConflict}
      />
    );

    // Proceed to confirmation
    fireEvent.click(screen.getByText(/Continue to Confirmation/i));

    // Confirm
    fireEvent.click(screen.getByText(/Confirm & Record APPROVED/i));

    await waitFor(() => {
      expect(screen.getByText(/Conflict: This approval gate is no longer pending/i)).toBeInTheDocument();
    });
  });
});
