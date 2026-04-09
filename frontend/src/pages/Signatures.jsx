import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { FileText, Send, CheckCircle, Clock, Plus, X, Upload } from 'lucide-react';

export default function Signatures() {
  const [templates, setTemplates] = useState([]);
  const [submissions, setSubmissions] = useState([]);
  const [configured, setConfigured] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [showSend, setShowSend] = useState(null); // template to send
  const [signers, setSigners] = useState([{ name: '', email: '' }]);
  const [message, setMessage] = useState('');
  const [uploading, setUploading] = useState(false);

  async function load() {
    const [status, tpl, subs] = await Promise.all([
      get('/signatures/status'),
      get('/signatures/templates'),
      get('/signatures/submissions'),
    ]);
    if (status) setConfigured(status.configured);
    if (tpl && Array.isArray(tpl)) setTemplates(tpl);
    if (subs && Array.isArray(subs)) setSubmissions(subs);
  }

  useEffect(() => { load(); }, []);

  async function handleUpload(e) {
    e.preventDefault();
    const form = e.target;
    const fileInput = form.querySelector('input[type="file"]');
    const nameInput = form.querySelector('input[name="name"]');
    if (!fileInput.files[0]) return;

    setUploading(true);
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('name', nameInput.value || fileInput.files[0].name);

    const res = await fetch('/api/signatures/templates', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${localStorage.getItem('shams_session')}` },
      body: formData,
    });
    setUploading(false);
    if (res.ok) {
      setShowUpload(false);
      load();
    }
  }

  async function handleSend(e) {
    e.preventDefault();
    const validSigners = signers.filter(s => s.email.trim());
    if (!validSigners.length || !showSend) return;

    await post('/signatures/send', {
      template_id: showSend.id,
      signers: validSigners,
      message,
    });
    setShowSend(null);
    setSigners([{ name: '', email: '' }]);
    setMessage('');
    load();
  }

  function addSigner() {
    setSigners(prev => [...prev, { name: '', email: '' }]);
  }

  function updateSigner(idx, field, value) {
    setSigners(prev => prev.map((s, i) => i === idx ? { ...s, [field]: value } : s));
  }

  function removeSigner(idx) {
    setSigners(prev => prev.filter((_, i) => i !== idx));
  }

  if (!configured) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <FileText size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
          <p className="text-sm text-[var(--text-muted)]">DocuSeal not configured</p>
          <p className="text-xs text-[var(--text-muted)] mt-1">Add DOCUSEAL_API_URL and DOCUSEAL_API_TOKEN to Railway env vars</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="mono-heading text-2xl text-[var(--text-primary)]">signatures</h1>
          <button onClick={() => setShowUpload(true)}
            className="text-xs px-3 py-1.5 rounded-lg bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)] hover:bg-[var(--accent)] hover:text-[var(--bg-deep)] transition-colors mono-heading flex items-center gap-1.5">
            <Upload size={12} /> upload document
          </button>
        </div>

        {/* Templates */}
        <div>
          <h3 className="mono-heading text-sm text-[var(--text-muted)] mb-3">templates</h3>
          {templates.length > 0 ? (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {templates.map(t => (
                <div key={t.id} className="glass-card p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <FileText size={14} className="text-[var(--accent)]" />
                    <span className="text-sm text-[var(--text-primary)] truncate">{t.name}</span>
                  </div>
                  <button onClick={() => { setShowSend(t); setSigners([{ name: '', email: '' }]); }}
                    className="text-[10px] px-2 py-1 rounded bg-[#22c55e20] text-[#22c55e] border border-[#22c55e30] hover:bg-[#22c55e30] mono-heading flex items-center gap-1">
                    <Send size={10} /> send for signing
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-[var(--text-muted)] text-center py-6">no templates yet — upload a PDF to get started</p>
          )}
        </div>

        {/* Submissions */}
        <div>
          <h3 className="mono-heading text-sm text-[var(--text-muted)] mb-3">signature requests</h3>
          {submissions.length > 0 ? (
            <div className="space-y-2">
              {submissions.map(s => {
                const submitters = s.submitters || s.signers || [];
                const allSigned = submitters.every(sub => sub.status === 'completed');
                return (
                  <div key={s.id} className="glass-card p-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        {allSigned ? <CheckCircle size={14} className="text-[#22c55e]" /> : <Clock size={14} className="text-[#f59e0b]" />}
                        <span className="text-sm text-[var(--text-primary)]">
                          {s.template?.name || `Submission #${s.id}`}
                        </span>
                      </div>
                      <span className={`text-[10px] px-2 py-0.5 rounded mono-heading ${
                        allSigned ? 'text-[#22c55e] bg-[#22c55e15]' : 'text-[#f59e0b] bg-[#f59e0b15]'
                      }`}>
                        {allSigned ? 'completed' : 'pending'}
                      </span>
                    </div>
                    <div className="space-y-1">
                      {submitters.map((sub, i) => (
                        <div key={i} className="flex items-center justify-between text-xs">
                          <span className="text-[var(--text-secondary)]">
                            {sub.name || sub.email}
                          </span>
                          <span className={`text-[10px] ${
                            sub.status === 'completed' ? 'text-[#22c55e]' : 'text-[#f59e0b]'
                          }`}>
                            {sub.status === 'completed' ? 'signed' : 'pending'}
                            {sub.completed_at && ` · ${new Date(sub.completed_at).toLocaleDateString()}`}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-xs text-[var(--text-muted)] text-center py-6">no signature requests yet</p>
          )}
        </div>
      </div>

      {/* Upload modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={() => setShowUpload(false)}>
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="mono-heading text-sm text-[var(--text-primary)]">upload document</h3>
              <button onClick={() => setShowUpload(false)} className="text-[var(--text-muted)]"><X size={16} /></button>
            </div>
            <form onSubmit={handleUpload} className="space-y-3">
              <input name="name" placeholder="document name" className="w-full px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] mono-heading placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]" />
              <input type="file" accept=".pdf" required className="w-full text-sm text-[var(--text-secondary)]" />
              <button type="submit" disabled={uploading}
                className="w-full py-2 rounded-lg bg-[var(--accent)] text-[var(--bg-deep)] mono-heading text-sm hover:bg-[#60ccf8] transition-colors disabled:opacity-50">
                {uploading ? 'uploading...' : 'upload'}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Send for signing modal */}
      {showSend && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={() => setShowSend(null)}>
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="mono-heading text-sm text-[var(--text-primary)]">send "{showSend.name}" for signing</h3>
              <button onClick={() => setShowSend(null)} className="text-[var(--text-muted)]"><X size={16} /></button>
            </div>
            <form onSubmit={handleSend} className="space-y-3">
              <div className="space-y-2">
                <span className="text-xs text-[var(--text-muted)] mono-heading">signers</span>
                {signers.map((s, i) => (
                  <div key={i} className="flex gap-2">
                    <input value={s.name} onChange={e => updateSigner(i, 'name', e.target.value)}
                      placeholder="name" className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] mono-heading placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]" />
                    <input value={s.email} onChange={e => updateSigner(i, 'email', e.target.value)}
                      placeholder="email" type="email" required className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] mono-heading placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]" />
                    {signers.length > 1 && (
                      <button type="button" onClick={() => removeSigner(i)} className="text-[var(--text-muted)]"><X size={14} /></button>
                    )}
                  </div>
                ))}
                <button type="button" onClick={addSigner}
                  className="text-[10px] text-[var(--accent)] mono-heading hover:underline flex items-center gap-1">
                  <Plus size={10} /> add signer
                </button>
              </div>
              <textarea value={message} onChange={e => setMessage(e.target.value)}
                placeholder="optional message to signers" rows={2}
                className="w-full px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] mono-heading placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] resize-none" />
              <button type="submit"
                className="w-full py-2 rounded-lg bg-[#22c55e] text-white mono-heading text-sm hover:bg-[#16a34a] transition-colors flex items-center justify-center gap-2">
                <Send size={14} /> send for signature
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
