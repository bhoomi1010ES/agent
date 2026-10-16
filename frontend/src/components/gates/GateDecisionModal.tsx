import React, { useState } from 'react';
import { APIError, decideGate } from '../../api/client';
import type { GateDecisionRequest, GateDetailResponse, WaiverRequest } from '../../types/api';
import { ErrorAlert } from '../common/ErrorAlert';
import { Modal } from '../common/Modal';

interface GateDecisionModalProps {
  isOpen: boolean;
  onClose: () => void;
  jobId: string;
  gate: GateDetailResponse;
  onDecisionRecorded: () => void;
  onConflict: () => void;
}

export const GateDecisionModal: React.FC<GateDecisionModalProps> = ({
  isOpen,
  onClose,
  jobId,
  gate,
  onDecisionRecorded,
  onConflict,
}) => {
  const [decision, setDecision] = useState<'approved' | 'rejected' | 'waived'>('approved');
  const [feedback, setFeedback] = useState('');
  const [waivers, setWaivers] = useState<WaiverRequest[]>([]);
  const [newWaiverSubject, setNewWaiverSubject] = useState('');
  const [newWaiverReason, setNewWaiverReason] = useState('');
  const [showWaiverInputs, setShowWaiverInputs] = useState(false);

  const [validationError, setValidationError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);

  const handleAddWaiver = () => {
    if (!newWaiverSubject.trim() || !newWaiverReason.trim()) {
      setValidationError('Both waiver subject and rationale are required.');
      return;
    }
    setWaivers([...waivers, { subject: newWaiverSubject.trim(), reason: newWaiverReason.trim() }]);
    setNewWaiverSubject('');
    setNewWaiverReason('');
    setShowWaiverInputs(false);
    setValidationError(null);
  };

  const handleRemoveWaiver = (index: number) => {
    setWaivers(waivers.filter((_, i) => i !== index));
  };

  const handleInitialSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);
    setServerError(null);

    if (decision === 'rejected' && (!feedback.trim() || feedback.trim().length < 5)) {
      setValidationError('Rejected decisions require constructive written feedback (min 5 characters).');
      return;
    }

    setIsConfirming(true);
  };

  const handleConfirmDecision = async () => {
    setIsSubmitting(true);
    setServerError(null);

    try {
      const payload: GateDecisionRequest = {
        decision,
        feedback: feedback.trim() ? feedback.trim() : null,
        waivers: waivers.length > 0 ? waivers : undefined,
      };

      await decideGate(jobId, gate.gate_id, payload);
      setIsConfirming(false);
      onClose();
      onDecisionRecorded();
    } catch (err: unknown) {
      setIsConfirming(false);
      if (err instanceof APIError && err.status === 409) {
        setServerError('Conflict: This approval gate is no longer pending or was resolved by another reviewer. Refreshing status...');
        setTimeout(() => {
          onConflict();
        }, 2000);
      } else {
        const msg = err instanceof Error ? err.message : 'Failed to record gate decision.';
        setServerError(msg);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Review Approval Gate: ${gate.gate_type}`}
      maxWidth="640px"
    >
      {serverError && <ErrorAlert message={serverError} />}
      {validationError && <ErrorAlert message={validationError} onDismiss={() => setValidationError(null)} />}

      {!isConfirming ? (
        <form onSubmit={handleInitialSubmit}>
          <div style={{ marginBottom: '1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem', fontSize: '0.85rem' }}>
              <div>
                Gate ID: <code className="code-snippet">{gate.gate_id.slice(0, 8)}...</code>
              </div>
              <div>
                Budget Used: <strong>${(gate.budget_used_cents / 100).toFixed(2)}</strong>
              </div>
            </div>

            {gate.needs_human_flags.length > 0 && (
              <div className="alert alert-warning" style={{ fontSize: '0.82rem', flexDirection: 'column', alignItems: 'flex-start' }}>
                <strong style={{ marginBottom: '0.25rem' }}>Automated Triggers Requiring Human Review:</strong>
                <ul style={{ paddingLeft: '1.25rem' }}>
                  {gate.needs_human_flags.map((flag, idx) => (
                    <li key={idx}>
                      <code>{flag.code || 'FLAG'}</code>: {flag.message || String(flag.details ? JSON.stringify(flag.details) : 'Review required')}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">Review Decision *</label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem' }}>
              <button
                type="button"
                className={`btn ${decision === 'approved' ? 'btn-success' : 'btn-secondary'}`}
                onClick={() => setDecision('approved')}
              >
                ✓ Approve
              </button>
              <button
                type="button"
                className={`btn ${decision === 'rejected' ? 'btn-danger' : 'btn-secondary'}`}
                onClick={() => setDecision('rejected')}
              >
                ✗ Reject
              </button>
              <button
                type="button"
                className={`btn ${decision === 'waived' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setDecision('waived')}
              >
                ⚠ Waive
              </button>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="gate-feedback">
              Reviewer Written Feedback {decision === 'rejected' ? '(Mandatory for rejection) *' : '(Optional)'}
            </label>
            <textarea
              id="gate-feedback"
              className="form-textarea"
              rows={4}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder={
                decision === 'rejected'
                  ? 'Detail the architectural gaps, test failures, or security concerns requiring agent remediation...'
                  : 'Add any optional reviewer comments or verification notes...'
              }
            />
          </div>

          {/* Waivers Section */}
          <div style={{ marginBottom: '1.5rem', borderTop: '1px solid var(--border-light)', paddingTop: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <label className="form-label" style={{ margin: 0 }}>
                Formal Waivers & Exceptions ({waivers.length})
              </label>
              {!showWaiverInputs && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setShowWaiverInputs(true)}
                >
                  + Add Waiver
                </button>
              )}
            </div>

            {waivers.map((w, idx) => (
              <div
                key={idx}
                style={{
                  padding: '0.5rem 0.75rem',
                  backgroundColor: 'var(--bg-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  marginBottom: '0.4rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontSize: '0.82rem',
                }}
              >
                <div>
                  <strong>{w.subject}</strong>: {w.reason}
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  style={{ padding: '0.1rem 0.4rem', fontSize: '0.7rem' }}
                  onClick={() => handleRemoveWaiver(idx)}
                >
                  Remove
                </button>
              </div>
            ))}

            {showWaiverInputs && (
              <div style={{ background: '#f8fafc', padding: '0.85rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', marginTop: '0.5rem' }}>
                <div className="form-group" style={{ marginBottom: '0.5rem' }}>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="Waiver subject (e.g. Non-blocking coverage gap in legacy utility)"
                    value={newWaiverSubject}
                    onChange={(e) => setNewWaiverSubject(e.target.value)}
                  />
                </div>
                <div className="form-group" style={{ marginBottom: '0.5rem' }}>
                  <textarea
                    className="form-textarea"
                    rows={2}
                    placeholder="Technical justification and risk mitigation reason..."
                    value={newWaiverReason}
                    onChange={(e) => setNewWaiverReason(e.target.value)}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setShowWaiverInputs(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={handleAddWaiver}
                  >
                    Attach Waiver
                  </button>
                </div>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '1rem' }}>
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" onClick={handleInitialSubmit}>
              Continue to Confirmation →
            </button>
          </div>
        </form>
      ) : (
        <div>
          <div className="alert alert-warning">
            <strong>Confirm Permanent Gate Decision:</strong> You are about to record an irreversible{' '}
            <strong style={{ textTransform: 'uppercase' }}>{decision}</strong> decision for{' '}
            <code>{gate.gate_type}</code>. This decision is immutably appended to the platform audit trail.
          </div>

          {feedback && (
            <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--bg-subtle)', borderRadius: 'var(--radius-md)', fontSize: '0.85rem' }}>
              <strong>Written Feedback:</strong>
              <p style={{ marginTop: '0.25rem', color: 'var(--text-secondary)' }}>{feedback}</p>
            </div>
          )}

          {waivers.length > 0 && (
            <div style={{ marginBottom: '1rem', fontSize: '0.82rem' }}>
              <strong>Included Waivers ({waivers.length}):</strong>
              <ul style={{ paddingLeft: '1.25rem', marginTop: '0.25rem' }}>
                {waivers.map((w, i) => (
                  <li key={i}>
                    <strong>{w.subject}</strong>: {w.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid var(--border-subtle)', paddingTop: '1.25rem' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setIsConfirming(false)}
              disabled={isSubmitting}
            >
              ← Back to Edit
            </button>
            <button
              type="button"
              className={`btn ${decision === 'approved' ? 'btn-success' : decision === 'rejected' ? 'btn-danger' : 'btn-primary'}`}
              onClick={handleConfirmDecision}
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Recording Decision...' : `Confirm & Record ${decision.toUpperCase()}`}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
};
