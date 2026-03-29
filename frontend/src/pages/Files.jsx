import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { FolderPlus, FileText, Image, Mic, File, ChevronRight, ArrowLeft } from 'lucide-react';

const typeIcons = {
  photo: Image,
  voice: Mic,
  pdf: FileText,
  document: File,
};

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
    setFolderPath(prev => [...prev, { id: currentFolder, name: folderPath.length ? folderPath[folderPath.length - 1]?.name : 'Root' }]);
    setCurrentFolder(folder.id);
    setSelectedFile(null);
  }

  function goBack() {
    const prev = folderPath.pop();
    setFolderPath([...folderPath]);
    setCurrentFolder(prev?.id || null);
    setSelectedFile(null);
  }

  async function handleCreateFolder(e) {
    e.preventDefault();
    if (!newFolder.trim()) return;
    await post('/folders', { name: newFolder.trim(), parent_id: currentFolder });
    setNewFolder('');
    load(currentFolder);
  }

  async function handleViewFile(fileId) {
    const data = await get(`/files/${fileId}`);
    if (data) setSelectedFile(data);
  }

  return (
    <div className="flex h-full">
      <div className={`${selectedFile ? 'w-1/2' : 'w-full'} p-6 border-r border-slate-700`}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {currentFolder && (
              <button onClick={goBack} className="text-slate-400 hover:text-white"><ArrowLeft size={18} /></button>
            )}
            <h2 className="text-lg font-semibold">Files</h2>
          </div>
          <form onSubmit={handleCreateFolder} className="flex gap-2">
            <input value={newFolder} onChange={e => setNewFolder(e.target.value)} placeholder="New folder"
              className="px-3 py-1.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm w-40 focus:outline-none focus:border-amber-400" />
            <button type="submit" className="px-2 py-1.5 bg-slate-700 hover:bg-slate-600 text-white rounded-lg"><FolderPlus size={14} /></button>
          </form>
        </div>

        {/* Folders */}
        {folders.length > 0 && (
          <div className="mb-4 space-y-1">
            {folders.map(f => (
              <button key={f.id} onClick={() => navigateToFolder(f)}
                className="w-full flex items-center gap-3 px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-left transition-colors">
                <FolderPlus size={16} className="text-amber-400" />
                <span className="text-sm text-slate-200 flex-1">{f.name}</span>
                <ChevronRight size={14} className="text-slate-500" />
              </button>
            ))}
          </div>
        )}

        {/* Files */}
        <div className="space-y-1">
          {files.map(f => {
            const Icon = typeIcons[f.file_type] || File;
            return (
              <button key={f.id} onClick={() => handleViewFile(f.id)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors ${
                  selectedFile?.id === f.id ? 'bg-slate-700 border border-amber-500/30' : 'bg-slate-800 hover:bg-slate-700'
                }`}>
                <Icon size={16} className="text-slate-400" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-slate-200 truncate">{f.filename}</p>
                  <p className="text-xs text-slate-500">{f.uploaded_at ? new Date(f.uploaded_at).toLocaleDateString() : ''}</p>
                </div>
                <span className="text-xs text-slate-600">{f.file_type}</span>
              </button>
            );
          })}
          {files.length === 0 && folders.length === 0 && (
            <p className="text-slate-500 text-sm py-4">No files yet. Send files to Shams via Telegram.</p>
          )}
        </div>
      </div>

      {/* File detail panel */}
      {selectedFile && (
        <div className="w-1/2 p-6 overflow-auto">
          <h3 className="text-md font-semibold mb-2">{selectedFile.filename}</h3>
          <div className="space-y-3 text-sm">
            <div className="flex gap-2">
              <span className="text-slate-500">Type:</span>
              <span className="text-slate-300">{selectedFile.file_type}</span>
            </div>
            <div className="flex gap-2">
              <span className="text-slate-500">MIME:</span>
              <span className="text-slate-300">{selectedFile.mime_type}</span>
            </div>
            <div className="flex gap-2">
              <span className="text-slate-500">Size:</span>
              <span className="text-slate-300">{(selectedFile.file_size / 1024).toFixed(1)} KB</span>
            </div>
            <div className="flex gap-2">
              <span className="text-slate-500">Uploaded:</span>
              <span className="text-slate-300">{new Date(selectedFile.uploaded_at).toLocaleString()}</span>
            </div>
            {selectedFile.summary && (
              <div>
                <p className="text-slate-500 mb-1">AI Summary:</p>
                <p className="text-slate-300 bg-slate-800 p-3 rounded-lg">{selectedFile.summary}</p>
              </div>
            )}
            {selectedFile.transcript && (
              <div>
                <p className="text-slate-500 mb-1">{selectedFile.file_type === 'voice' ? 'Transcript:' : 'Extracted Text:'}</p>
                <pre className="text-slate-300 bg-slate-800 p-3 rounded-lg whitespace-pre-wrap text-xs max-h-96 overflow-auto">{selectedFile.transcript}</pre>
              </div>
            )}
            {selectedFile.tags && selectedFile.tags.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                {selectedFile.tags.map((t, i) => (
                  <span key={i} className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded">{t}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
