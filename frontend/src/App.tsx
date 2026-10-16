import React, { useEffect, useState } from 'react';
import { DashboardView } from './components/dashboard/DashboardView';
import { JobCreateModal } from './components/jobs/JobCreateModal';
import { JobDetailView } from './components/jobs/JobDetailView';
import { AuthBar } from './components/layout/AuthBar';
import { Header } from './components/layout/Header';

export const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<'dashboard' | 'create' | 'job-detail'>('dashboard');
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Sync hash routing on mount and hashchange
  useEffect(() => {
    const parseHash = () => {
      const hash = window.location.hash;
      if (hash.startsWith('#/jobs/')) {
        const jobId = hash.replace('#/jobs/', '');
        if (jobId) {
          setSelectedJobId(jobId);
          setCurrentView('job-detail');
          return;
        }
      }
      if (hash === '#/create') {
        setIsCreateModalOpen(true);
        setCurrentView('dashboard');
        return;
      }
      setSelectedJobId(null);
      setCurrentView('dashboard');
    };

    parseHash();
    window.addEventListener('hashchange', parseHash);
    return () => window.removeEventListener('hashchange', parseHash);
  }, []);

  const handleSelectJob = (jobId: string) => {
    setSelectedJobId(jobId);
    setCurrentView('job-detail');
    window.location.hash = `#/jobs/${jobId}`;
  };

  const handleNavigate = (view: 'dashboard' | 'create') => {
    if (view === 'create') {
      setIsCreateModalOpen(true);
    } else {
      setSelectedJobId(null);
      setCurrentView('dashboard');
      window.location.hash = '';
    }
  };

  const handleJobCreated = (newJobId: string) => {
    setRefreshTrigger((prev) => prev + 1);
    handleSelectJob(newJobId);
  };

  const handleSessionChange = () => {
    setRefreshTrigger((prev) => prev + 1);
  };

  return (
    <div className="app-container">
      {/* Top Session & Authorization Bar */}
      <AuthBar onSessionChange={handleSessionChange} />

      {/* Main Navigation Header */}
      <Header
        currentView={currentView}
        onNavigate={handleNavigate}
        selectedJobId={selectedJobId}
      />

      {/* Main Content Body */}
      <main className="main-content">
        {currentView === 'dashboard' && (
          <DashboardView
            onSelectJob={handleSelectJob}
            onCreateJob={() => setIsCreateModalOpen(true)}
            refreshTrigger={refreshTrigger}
          />
        )}

        {currentView === 'job-detail' && selectedJobId && (
          <JobDetailView
            jobId={selectedJobId}
            onBack={() => handleNavigate('dashboard')}
          />
        )}
      </main>

      {/* Intake Job Modal */}
      <JobCreateModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onJobCreated={handleJobCreated}
      />
    </div>
  );
};

export default App;
