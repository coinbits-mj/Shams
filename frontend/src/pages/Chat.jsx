import { useState, useRef, useEffect } from 'react';
import { post, get, upload } from '../api';
import { Send, Paperclip, X, FileText, Image } from 'lucide-react';
import SmartMessage from '../components/SmartMessage';

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => { get('/conversations?limit=30').then(d => d && setMessages(d)); }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  function handleFiles(e) {
    const selected = Array.from(e.target.files);
    setFiles(prev => [...prev, ...selected]);
    e.target.value = '';
  }

  function removeFile(idx) {
    setFiles(prev => prev.filter((_, i) => i !== idx));
  }

  async function handleSend(e) {
    e.preventDefault();
    if ((!input.trim() && files.length === 0) || loading) return;
    const msg = input.trim();
    const attachedFiles = [...files];
    setInput('');
    setFiles([]);

    const label = attachedFiles.length > 0
      ? `${msg || ''}${msg ? ' ' : ''}[${attachedFiles.map(f => f.name).join(', ')}]`
      : msg;
    setMessages(prev => [...prev, { role: 'user', content: label }]);
    setLoading(true);

    let data;
    if (attachedFiles.length > 0) {
      data = await upload('/chat', msg, attachedFiles);
    } else {
      data = await post('/chat', { message: msg });
    }
    if (data?.reply) setMessages(prev => [...prev, { role: 'assistant', content: data.reply }]);
    setLoading(false);
  }

  function handleDrop(e) {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length) setFiles(prev => [...prev, ...dropped]);
  }

  return (
    <div className="flex flex-col h-full" onDragOver={e => e.preventDefault()} onDrop={handleDrop}>
      <div className="border-b border-[var(--border)] px-6 py-4">
        <h2 className="mono-heading text-lg">chat with shams</h2>
      </div>
      <div className="flex-1 overflow-auto px-6 py-4 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[75%] rounded-xl px-4 py-3 text-sm whitespace-pre-wrap ${
              m.role === 'user'
                ? 'bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)]'
                : 'glass-card text-[var(--text-primary)]'
            }`}>
              <SmartMessage content={m.content} />
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="glass-card rounded-xl px-4 py-3 text-sm text-[var(--text-muted)]">
              <span className="pulse-active inline-block">thinking...</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* File preview */}
      {files.length > 0 && (
        <div className="px-6 py-2 border-t border-[var(--border)] flex gap-2 flex-wrap">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] text-xs text-[var(--text-secondary)]">
              {f.type?.startsWith('image/') ? <Image size={12} /> : <FileText size={12} />}
              <span className="max-w-[120px] truncate">{f.name}</span>
              <button onClick={() => removeFile(i)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={handleSend} className="border-t border-[var(--border)] px-6 py-4 flex gap-3">
        <input type="file" ref={fileRef} onChange={handleFiles} multiple accept="image/*,.pdf,.doc,.docx,.txt,.md,.csv,.json" className="hidden" />
        <button type="button" onClick={() => fileRef.current?.click()}
          className="px-3 py-3 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
          <Paperclip size={16} />
        </button>
        <input type="text" value={input} onChange={e => setInput(e.target.value)}
          placeholder="message shams..."
          className="flex-1 px-4 py-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] mono-heading text-sm" />
        <button type="submit" disabled={loading}
          className="px-4 py-3 bg-[var(--accent)] hover:bg-[#60ccf8] text-[var(--bg-deep)] rounded-xl transition-colors disabled:opacity-50">
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
