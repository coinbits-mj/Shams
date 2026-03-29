import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { FolderPlus, FileText, Image, Mic, File, ChevronRight, ArrowLeft } from 'lucide-react';

const typeIcons = { photo: Image, voice: Mic, pdf: FileText, document: File };

export default function Files() {
  const [folders, setFolders] = useState([]);
  const [files, setFiles] = useState([]);
  const [currentFolder, setCurrentFolder] = useState(null);
  const [folderPath, setFolderPath] = useState([]);
  const [newFolder, setNewFolder] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);

  async function load(folderId = null) {
    const [f, fi] = await Promise.all([
      get(`/folders${folderId ? `?parent_id=${folderId}` : ''}`),
      get(`/files${folderId ? `?folder_id=${folderId}` : ''}`)
    ]);
    if (f) setFolders(f);
    if (fi) setFiles(fi);
  }
  useEffect(() => { load(currentFolder); }, [currentFolder]);

  function navigateToFolder(folder) {
    setFolderPath(prev => [...prev, { id: currentFolder }]);
    setCurrentFolder(folder.id);
    setSelectedFile(null);
  }
  function goBack() {
    const prev = folderPath.pop();
    setFolderPath([...folderPath]);
    setCurrentFolder(prev?.id || null);
    setSelectedFile(null);
  }

  return (
    <div className="flex h-full">
      <div className={`${selectedFile ? 'w-1/2' : 'w-full'} p-6 border-r border-[var(--border)]`}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {currentFolder && <button onClick={goBack} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"><ArrowLeft size={16} /></button>}
            <h2 className="mono-heading text-lg">files</h2>
          </div>
          <form onSubmit={e => { e.preventDefault(); if (newFolder.trim()) { post('/folders', { name: newFolder.trim(), parent_id: currentFolder }).then(() => { setNewFolder(''); load(currentFolder); }); }}} className="flex gap-2">
            <input value={newFolder} onChange={e => setNewFolder(e.target.value)} placeholder="new folder"
              className="px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm w-36 focus:outline-none focus:border-[var(--accent)] mono-heading placeholder:text-[var(--text-muted)]" />
            <button type="submit" className="px-2 py-1.5 bg-[var(--bg-card)] hover:bg-[var(--bg-hover)] border border-[var(--border)] text-[var(--text-primary)] rounded-lg"><FolderPlus size={13} /></button>
          </form>
        </div>
        {folders.map(f => (
          <button key={f.id} onClick={() => navigateToFolder(f)}
            className="w-full flex items-center gap-3 px-3 py-2 glass-card mb-1 text-left">
            <FolderPlus size={14} className="text-[var(--amber)]" />
            <span className="text-sm text-[var(--text-primary)] flex-1">{f.name}</span>
            <ChevronRight size={12} className="text-[var(--text-muted)]" />
          </button>
        ))}
        <div className="space-y-1 mt-2">
          {files.map(f => {
            const Icon = typeIcons[f.file_type] || File;
            return (
              <button key={f.id} onClick={() => get(`/files/${f.id}`).then(d => d && setSelectedFile(d))}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all ${
                  selectedFile?.id === f.id ? 'glass-card border-[var(--accent)]' : 'hover:bg-[var(--bg-hover)]'
                }`}>
                <Icon size={14} className="text-[var(--text-muted)]" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-[var(--text-primary)] truncate">{f.filename}</p>
                  <p className="text-[10px] text-[var(--text-muted)]">{f.uploaded_at ? new Date(f.uploaded_at).toLocaleDateString() : ''}</p>
                </div>
                <span className="mono-heading text-[10px] text-[var(--text-muted)]">{f.file_type}</span>
              </button>
            );
          })}
          {files.length === 0 && folders.length === 0 && <p className="text-[var(--text-muted)] text-sm py-4">no files yet. send files to shams via telegram.</p>}
        </div>
      </div>
      {selectedFile && (
        <div className="w-1/2 p-6 overflow-auto">
          <h3 className="mono-heading text-md mb-3">{selectedFile.filename}</h3>
          <div className="space-y-3 text-sm">
            <div className="flex gap-2"><span className="text-[var(--text-muted)]">type:</span><span className="text-[var(--text-secondary)]">{selectedFile.file_type}</span></div>
            <div className="flex gap-2"><span className="text-[var(--text-muted)]">size:</span><span className="text-[var(--text-secondary)]">{(selectedFile.file_size / 1024).toFixed(1)} KB</span></div>
            <div className="flex gap-2"><span className="text-[var(--text-muted)]">uploaded:</span><span className="text-[var(--text-secondary)]">{new Date(selectedFile.uploaded_at).toLocaleString()}</span></div>
            {selectedFile.summary && (
              <div><p className="text-[var(--text-muted)] mb-1">ai summary:</p><p className="text-[var(--text-secondary)] glass-card p-3">{selectedFile.summary}</p></div>
            )}
            {selectedFile.transcript && (
              <div><p className="text-[var(--text-muted)] mb-1">{selectedFile.file_type === 'voice' ? 'transcript:' : 'extracted text:'}</p>
              <pre className="text-[var(--text-secondary)] glass-card p-3 whitespace-pre-wrap text-xs max-h-96 overflow-auto">{selectedFile.transcript}</pre></div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
