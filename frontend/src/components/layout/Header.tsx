import React from 'react';

interface HeaderProps {
  currentView: 'dashboard' | 'create' | 'job-detail';
  onNavigate: (view: 'dashboard' | 'create') => void;
  selectedJobId?: string | null;
}

export const Header: React.FC<HeaderProps> = ({
  currentView,
  onNavigate,
  selectedJobId,
}) => {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand-section">
          <div className="brand-logo" onClick={() => onNavigate('dashboard')} role="button" tabIndex={0}>
            <div className="brand-icon-wrapper">
              <span style={{ fontSize: '1.15rem' }}>⚡</span>
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ letterSpacing: '-0.02em' }}>Modernization Platform</span>
                <span className="brand-badge">Studio</span>
              </div>
              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', fontWeight: 500, letterSpacing: '0.02em' }}>
                Autonomous Legacy Modernization Engine
              </div>
            </div>
          </div>

          {selectedJobId && currentView === 'job-detail' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              <span>/</span>
              <span>Job:</span>
              <code className="code-snippet">{selectedJobId.slice(0, 8)}...</code>
            </div>
          )}
        </div>

        {/* Live Swarm Telemetry Ribbon */}
        <div className="swarm-radar-ribbon" title="Active Multi-Agent Swarm Workers">
          <span className="swarm-radar-title">
            <span className="radar-dot"></span>
            Swarm:
          </span>
          <span className="swarm-agent-pill active" title="Supervisor Agent: DAG orchestrator active">
            Supervisor
          </span>
          <span className="swarm-agent-pill active" title="AST Analyzer: Tree-sitter parser active">
            AST Analyzer
          </span>
          <span className="swarm-agent-pill busy" title="Feasibility: Gate G1 approval pending">
            <span className="radar-dot amber" style={{ width: 5, height: 5 }}></span>
            Gate G1
          </span>
          <span className="swarm-agent-pill active" title="Equivalence Agent: 99.6% Parity verified">
            Equivalence
          </span>
        </div>

        <nav className="nav-links" aria-label="Main Navigation">
          <button
            type="button"
            className={`nav-btn ${currentView === 'dashboard' ? 'active' : ''}`}
            onClick={() => onNavigate('dashboard')}
          >
            📋 All Jobs
          </button>
          <button
            type="button"
            className={`btn btn-primary btn-sm ${currentView === 'create' ? 'active' : ''}`}
            onClick={() => onNavigate('create')}
          >
            + New Intake Job
          </button>
        </nav>
      </div>
    </header>
  );
};
