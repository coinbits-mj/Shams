import { useState, useEffect } from 'react';
import { get } from '../api';
import { X, FileText, Download } from 'lucide-react';

export default function FilePreviewModal({ fileId, onClose }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!fileId) return;
    setLoading(true);
    get(`/files/${fileId}`).then(data => {
      if (data) setFile(data);
      setLoading(false);
    });
  }, [fileId]);

  if (!fileId) return null;

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl max-w-3xl w-full max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <FileText size={16} className="text-[var(--accent)]" />
            <h3 className="text-sm text-[var(--text-primary)] mono-heading">
              {loading ? 'loading...' : (file?.filename || `file #${fileId}`)}
            </h3>
            {file?.file_type && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent-glow)] text-[var(--accent)] uppercase mono-heading">
                {file.file_type.replace('_', ' ')}
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <X size={16} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {loading && (
            <p className="text-sm text-[var(--text-muted)] text-center py-8">loading document...</p>
          )}
          {!loading && !file && (
            <p className="text-sm text-[var(--text-muted)] text-center py-8">file not found</p>
          )}
          {file && (
            <div className="space-y-3">
              {file.summary && (
                <div className="text-xs text-[var(--text-muted)]">{file.summary}</div>
              )}
              {file.transcript ? (
                <div className="bg-[var(--bg-deep)] p-4 rounded-lg border border-[var(--border)] text-sm text-[var(--text-primary)] whitespace-pre-wrap leading-relaxed max-h-[60vh] overflow-y-auto">
                  {file.transcript}
                </div>
              ) : (
                <p className="text-sm text-[var(--text-muted)] text-center py-4">no preview available</p>
              )}
              <div className="text-[10px] text-[var(--text-muted)] flex items-center gap-3">
                <span>{file.mime_type}</span>
                {file.file_size > 0 && <span>{(file.file_size / 1024).toFixed(1)} KB</span>}
                {file.uploaded_at && <span>{new Date(file.uploaded_at).toLocaleString()}</span>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
