import { useState, useEffect } from 'react';
import { get, post, del } from '../api';
import { Plus, Trash2 } from 'lucide-react';

export default function Memory() {
  const [memories, setMemories] = useState({});
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');

  async function load() { const d = await get('/memory'); if (d) setMemories(d); }
  useEffect(() => { load(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    if (!key.trim() || !value.trim()) return;
    await post('/memory', { key: key.trim(), value: value.trim() });
    setKey(''); setValue(''); load();
  }

  return (
    <div className="p-6">
      <h2 className="mono-heading text-lg mb-4">persistent memory</h2>
      <form onSubmit={handleAdd} className="flex gap-2 mb-6">
        <input value={key} onChange={e => setKey(e.target.value)} placeholder="key"
          className="px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm w-48 focus:outline-none focus:border-[var(--accent)] mono-heading placeholder:text-[var(--text-muted)]" />
        <input value={value} onChange={e => setValue(e.target.value)} placeholder="value"
          className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-[var(--accent)] mono-heading placeholder:text-[var(--text-muted)]" />
        <button type="submit" className="px-3 py-2 bg-[var(--accent)] text-[var(--bg-deep)] rounded-lg hover:bg-[#60ccf8]"><Plus size={14} /></button>
      </form>
      <div className="space-y-2">
        {Object.entries(memories).map(([k, v]) => (
          <div key={k} className="glass-card flex items-start gap-3 p-3">
            <div className="flex-1">
              <span className="mono-heading text-sm text-[var(--accent)]">{k}</span>
              <p className="text-[var(--text-secondary)] text-sm mt-1">{v}</p>
            </div>
            <button onClick={() => { del(`/memory/${encodeURIComponent(k)}`).then(load); }}
              className="text-[var(--text-muted)] hover:text-[var(--red)] mt-1"><Trash2 size={13} /></button>
          </div>
        ))}
        {Object.keys(memories).length === 0 && <p className="text-[var(--text-muted)] text-sm">no memories stored yet. talk to shams — he'll start remembering.</p>}
      </div>
    </div>
  );
}
