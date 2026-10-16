import React, { useState } from 'react';
import { getActiveRole, getActiveTenantId, getAuthToken, setActiveRole, setActiveTenantId, setAuthToken } from '../../api/client';
import { Modal } from '../common/Modal';

interface AuthBarProps {
  onSessionChange: () => void;
}

export const AuthBar: React.FC<AuthBarProps> = ({ onSessionChange }) => {
  const [isConfigOpen, setIsConfigOpen] = useState(false);
  const [tokenInput, setTokenInput] = useState(getAuthToken());
  const [roleInput, setRoleInput] = useState(getActiveRole());
  const [tenantInput, setTenantInput] = useState(getActiveTenantId());

  const currentRole = getActiveRole();
  const currentToken = getAuthToken();
  const currentTenant = getActiveTenantId();

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setAuthToken(tokenInput.trim());
    setActiveRole(roleInput);
    setActiveTenantId(tenantInput.trim());
    setIsConfigOpen(false);
    onSessionChange();
  };

  const handleClear = () => {
    setAuthToken('');
    setTokenInput('');
    setIsConfigOpen(false);
    onSessionChange();
  };

  return (
    <>
      <div className="auth-bar">
        <div className="auth-bar-inner">
          <div className="auth-info">
            <span style={{ color: '#94a3b8' }}>Session:</span>
            <span className={`role-badge ${currentRole}`}>{currentRole}</span>
            <span style={{ color: '#64748b', fontSize: '0.78rem' }}>
              Tenant: <code style={{ color: '#cbd5e1' }}>{currentTenant.slice(0, 8)}...</code>
            </span>
            <span style={{ fontSize: '0.78rem', color: currentToken ? '#34d399' : '#f87171' }}>
              {currentToken ? '● Authenticated' : '○ No Token Configured'}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setIsConfigOpen(true)}
              style={{
                backgroundColor: '#1e293b',
                color: '#f8fafc',
                borderColor: '#334155',
                padding: '0.2rem 0.6rem',
                fontSize: '0.75rem',
              }}
            >
              ⚙ Auth & Role Settings
            </button>
          </div>
        </div>
      </div>

      <Modal
        isOpen={isConfigOpen}
        onClose={() => setIsConfigOpen(false)}
        title="Session Authorization & Role Configuration"
      >
        <form onSubmit={handleSave}>
          <div className="alert alert-info">
            Configure your active role and Bearer JWT token to test role-based access control (RBAC), tenant isolation, and approval gate authorization against the live API.
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="role-select">
              Active Role
            </label>
            <select
              id="role-select"
              className="form-select"
              value={roleInput}
              onChange={(e) => setRoleInput(e.target.value)}
            >
              <option value="reviewer">Reviewer (View jobs, artifacts, gates)</option>
              <option value="approver">Approver (View jobs, artifacts, gates, decide gates)</option>
              <option value="owner">Owner (Create/manage jobs, view artifacts, decide gates, view audit)</option>
              <option value="admin">Admin (Full tenant administration)</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="tenant-input">
              Tenant ID
            </label>
            <input
              id="tenant-input"
              type="text"
              className="form-input"
              value={tenantInput}
              onChange={(e) => setTenantInput(e.target.value)}
              placeholder="e.g. 00000000-0000-0000-0000-000000000001"
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="token-input">
              Bearer JWT Token
            </label>
            <textarea
              id="token-input"
              className="form-textarea"
              rows={4}
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Paste RS256 JWT access token here. Tokens are kept securely in sessionStorage and never logged."
            />
            <div className="form-hint">
              When empty, requests will be issued unauthenticated, allowing you to test 401 Unauthorized handling.
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '1.5rem' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleClear}
              style={{ color: '#dc2626' }}
            >
              Clear Token
            </button>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setIsConfigOpen(false)}
              >
                Cancel
              </button>
              <button type="submit" className="btn btn-primary btn-sm">
                Save & Apply
              </button>
            </div>
          </div>
        </form>
      </Modal>
    </>
  );
};
