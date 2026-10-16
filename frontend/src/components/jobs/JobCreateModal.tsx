import React, { useState } from 'react';
import { createJob } from '../../api/client';
import type { JobCreateRequest } from '../../types/api';
import { ErrorAlert } from '../common/ErrorAlert';
import { Modal } from '../common/Modal';

interface JobCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onJobCreated: (jobId: string) => void;
}

export const JobCreateModal: React.FC<JobCreateModalProps> = ({
  isOpen,
  onClose,
  onJobCreated,
}) => {
  const [sourceRepo, setSourceRepo] = useState('https://github.com/legacy-org/monolith-core');
  const [sourceRevision, setSourceRevision] = useState('main');
  const [targetRuntime, setTargetRuntime] = useState('python3.12');
  const [targetFramework, setTargetFramework] = useState('fastapi');
  const [targetArchitecture, setTargetArchitecture] = useState('modular-monolith');
  const [maxCostUsd, setMaxCostUsd] = useState('500.00');
  const [maxDurationSecs, setMaxDurationSecs] = useState('7200');

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validate = (): boolean => {
    const errors: Record<string, string> = {};

    if (!sourceRepo.trim()) {
      errors.sourceRepo = 'Source repository is required.';
    } else if (sourceRepo.trim().length < 3) {
      errors.sourceRepo = 'Repository path or URL must be at least 3 characters.';
    }

    if (!sourceRevision.trim()) {
      errors.sourceRevision = 'Revision (branch, commit, or tag) is required.';
    }

    if (!targetRuntime.trim()) {
      errors.targetRuntime = 'Target runtime is required.';
    }

    if (!targetFramework.trim()) {
      errors.targetFramework = 'Target framework is required.';
    }

    const cost = parseFloat(maxCostUsd);
    if (isNaN(cost) || cost <= 0) {
      errors.maxCostUsd = 'Max cost must be a positive number greater than 0.';
    }

    const duration = parseInt(maxDurationSecs, 10);
    if (isNaN(duration) || duration <= 0) {
      errors.maxDurationSecs = 'Duration must be a positive integer in seconds.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setServerError(null);

    if (!validate()) return;

    setIsSubmitting(true);
    try {
      const payload: JobCreateRequest = {
        source_repository: sourceRepo.trim(),
        source_revision: sourceRevision.trim(),
        target_stack: {
          runtime: targetRuntime.trim(),
          framework: targetFramework.trim(),
          architecture: targetArchitecture.trim(),
        },
        budget: {
          max_total_cost_usd: parseFloat(maxCostUsd),
          max_duration_seconds: parseInt(maxDurationSecs, 10),
        },
      };

      const response = await createJob(payload);
      onClose();
      onJobCreated(response.job_id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to create job';
      setServerError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Intake New Modernization Job"
      maxWidth="680px"
    >
      <form onSubmit={handleSubmit}>
        {serverError && <ErrorAlert message={serverError} />}

        <div className="alert alert-info" style={{ fontSize: '0.82rem' }}>
          <strong>Notice:</strong> Submitting this intake form registers and persists the modernization job configuration in the PostgreSQL control plane. LangGraph agent workers lease and process jobs in subsequent stages.
        </div>

        {/* Modernization Presets */}
        <div style={{ marginBottom: '1.25rem' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem' }}>
            ⚡ 1-Click Modernization Presets
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ fontSize: '0.75rem', padding: '0.4rem 0.5rem', textAlign: 'left', display: 'flex', flexDirection: 'column', gap: '0.15rem' }}
              onClick={() => {
                setSourceRepo('https://github.com/apex-financial/core-settlement-engine');
                setSourceRevision('v2.4-legacy');
                setTargetRuntime('python3.12');
                setTargetFramework('fastapi');
                setTargetArchitecture('modular-monolith');
                setMaxCostUsd('1250.00');
                setMaxDurationSecs('14400');
              }}
            >
              <span style={{ fontWeight: 700, color: '#a5b4fc' }}>🏦 Banking Core</span>
              <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Java 8 ➔ FastAPI</span>
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ fontSize: '0.75rem', padding: '0.4rem 0.5rem', textAlign: 'left', display: 'flex', flexDirection: 'column', gap: '0.15rem' }}
              onClick={() => {
                setSourceRepo('https://github.com/aegis-insurance/claims-underwriting-core');
                setSourceRevision('cics-prod');
                setTargetRuntime('go1.22');
                setTargetFramework('gin');
                setTargetArchitecture('microservices');
                setMaxCostUsd('2500.00');
                setMaxDurationSecs('28800');
              }}
            >
              <span style={{ fontWeight: 700, color: '#38bdf8' }}>🛡️ Insurance Core</span>
              <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>COBOL ➔ Go Microservices</span>
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ fontSize: '0.75rem', padding: '0.4rem 0.5rem', textAlign: 'left', display: 'flex', flexDirection: 'column', gap: '0.15rem' }}
              onClick={() => {
                setSourceRepo('https://github.com/omni-retail/order-checkout-service');
                setSourceRevision('release-1.8');
                setTargetRuntime('node20');
                setTargetFramework('nestjs-typescript');
                setTargetArchitecture('clean-architecture');
                setMaxCostUsd('600.00');
                setMaxDurationSecs('7200');
              }}
            >
              <span style={{ fontWeight: 700, color: '#34d399' }}>🛒 Retail Checkout</span>
              <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>PHP 5.6 ➔ NestJS</span>
            </button>
          </div>
        </div>

        {/* Section 1: Source Repository */}
        <div style={{ marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '0.92rem', fontWeight: 700, marginBottom: '0.75rem', color: 'var(--text-primary)' }}>
            1. Source Codebase
          </h3>
          <div className="form-group">
            <label className="form-label" htmlFor="source-repo-input">
              Source Repository Path or URL *
            </label>
            <input
              id="source-repo-input"
              type="text"
              className="form-input"
              value={sourceRepo}
              onChange={(e) => setSourceRepo(e.target.value)}
              placeholder="e.g. https://github.com/legacy-org/monolith-core or /repos/legacy"
              disabled={isSubmitting}
            />
            {fieldErrors.sourceRepo && <div className="form-error">{fieldErrors.sourceRepo}</div>}
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="source-rev-input">
              Source Revision / Branch *
            </label>
            <input
              id="source-rev-input"
              type="text"
              className="form-input"
              value={sourceRevision}
              onChange={(e) => setSourceRevision(e.target.value)}
              placeholder="e.g. main, v1.4.2, or commit SHA"
              disabled={isSubmitting}
            />
            {fieldErrors.sourceRevision && <div className="form-error">{fieldErrors.sourceRevision}</div>}
          </div>
        </div>

        {/* Section 2: Target Technology Stack */}
        <div style={{ marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '0.92rem', fontWeight: 700, marginBottom: '0.75rem', color: 'var(--text-primary)' }}>
            2. Target Technology Stack
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="target-runtime-input">
                Target Runtime *
              </label>
              <input
                id="target-runtime-input"
                type="text"
                className="form-input"
                value={targetRuntime}
                onChange={(e) => setTargetRuntime(e.target.value)}
                placeholder="e.g. python3.12, node20, java21"
                disabled={isSubmitting}
              />
              {fieldErrors.targetRuntime && <div className="form-error">{fieldErrors.targetRuntime}</div>}
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="target-framework-input">
                Target Framework *
              </label>
              <input
                id="target-framework-input"
                type="text"
                className="form-input"
                value={targetFramework}
                onChange={(e) => setTargetFramework(e.target.value)}
                placeholder="e.g. fastapi, spring-boot, nextjs"
                disabled={isSubmitting}
              />
              {fieldErrors.targetFramework && <div className="form-error">{fieldErrors.targetFramework}</div>}
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="target-arch-select">
              Architecture Pattern
            </label>
            <select
              id="target-arch-select"
              className="form-select"
              value={targetArchitecture}
              onChange={(e) => setTargetArchitecture(e.target.value)}
              disabled={isSubmitting}
            >
              <option value="modular-monolith">Modular Monolith (Recommended)</option>
              <option value="clean-architecture">Clean Architecture / Domain-Driven</option>
              <option value="microservices">Microservices</option>
              <option value="serverless">Serverless Functions</option>
            </select>
          </div>
        </div>

        {/* Section 3: Guardrail Budget */}
        <div style={{ marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '0.92rem', fontWeight: 700, marginBottom: '0.75rem', color: 'var(--text-primary)' }}>
            3. Guardrail Budget
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="max-cost-input">
                Max Cost Limit (USD) *
              </label>
              <input
                id="max-cost-input"
                type="number"
                step="0.01"
                min="1.00"
                className="form-input"
                value={maxCostUsd}
                onChange={(e) => setMaxCostUsd(e.target.value)}
                disabled={isSubmitting}
              />
              {fieldErrors.maxCostUsd && <div className="form-error">{fieldErrors.maxCostUsd}</div>}
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="max-duration-input">
                Max Duration (Seconds) *
              </label>
              <input
                id="max-duration-input"
                type="number"
                step="60"
                min="60"
                className="form-input"
                value={maxDurationSecs}
                onChange={(e) => setMaxDurationSecs(e.target.value)}
                disabled={isSubmitting}
              />
              <div className="form-hint">
                ≈ {Math.round(parseInt(maxDurationSecs || '0', 10) / 60)} minutes
              </div>
              {fieldErrors.maxDurationSecs && <div className="form-error">{fieldErrors.maxDurationSecs}</div>}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '1.25rem' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={isSubmitting}
            onClick={handleSubmit}
          >
            {isSubmitting ? 'Creating Job...' : 'Create & Persist Job'}
          </button>
        </div>
      </form>
    </Modal>
  );
};
