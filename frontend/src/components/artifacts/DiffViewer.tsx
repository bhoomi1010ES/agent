import React from 'react';

interface DiffViewerProps {
  diffText: string;
  filename?: string;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ diffText, filename }) => {
  const lines = (diffText || '').split('\n');

  return (
    <div className="diff-container" style={{ background: '#070b12', border: '1px solid var(--border-light)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
      {filename && (
        <div
          style={{
            padding: '0.6rem 1rem',
            background: 'var(--bg-surface)',
            fontWeight: 600,
            fontSize: '0.82rem',
            borderBottom: '1px solid var(--border-light)',
            color: '#e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>📄</span>
            <code style={{ color: '#38bdf8', fontFamily: 'var(--font-mono)' }}>{filename}</code>
          </div>
          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Unified Modernization Diff</span>
        </div>
      )}
      <div style={{ padding: '0.5rem 0', fontFamily: 'var(--font-mono)', fontSize: '0.82rem', overflowX: 'auto' }}>
        {lines.map((line, index) => {
          let lineType = 'normal';
          let lineBg = 'transparent';
          let textColor = '#cbd5e1';

          if (line.startsWith('+') && !line.startsWith('+++')) {
            lineType = 'added';
            lineBg = 'rgba(16, 185, 129, 0.15)';
            textColor = '#86efac';
          } else if (line.startsWith('-') && !line.startsWith('---')) {
            lineType = 'removed';
            lineBg = 'rgba(239, 68, 68, 0.15)';
            textColor = '#fca5a5';
          } else if (line.startsWith('@@')) {
            lineType = 'header';
            lineBg = 'rgba(99, 102, 241, 0.1)';
            textColor = '#818cf8';
          }

          return (
            <div
              key={index}
              className={`diff-line ${lineType}`}
              style={{
                backgroundColor: lineBg,
                color: textColor,
                display: 'flex',
                padding: '0.12rem 0',
                lineHeight: 1.5,
              }}
            >
              <span
                style={{
                  display: 'inline-block',
                  width: '3.5rem',
                  color: '#64748b',
                  userSelect: 'none',
                  textAlign: 'right',
                  paddingRight: '0.85rem',
                }}
              >
                {index + 1}
              </span>
              <span style={{ whiteSpace: 'pre', flex: 1 }}>{line || ' '}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
