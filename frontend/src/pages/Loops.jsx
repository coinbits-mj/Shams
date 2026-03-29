import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { Plus, Check, X } from 'lucide-react';

export default function Loops() {
  const [loops, setLoops] = useState([]);
  const [title, setTitle] = useState('');
  const [context, setContext] = useState('');
  const [showAll, setShowAll] = useState(false);

  async function load() { const d = await get(`/loops?status=${showAll ? 'all' : 'open'}`); if (d) setLoops(d); }
  useEffect(() => { load(); }, [showAll]);

  async function handleAdd(e) {
    e.preventDefault();
    if (!title.trim()) return;
    await post('/loops', { title: title.trim(), context: context.trim() });
    setTitle(''); setContext(''); load();
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="mono-heading text-lg">open loops</h2>
        <button onClick={() => setShowAll(!showAll)}
          className="mono-heading text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] px-3 py-1 border border-[var(--border)] rounded-lg">
          {showAll ? 'open only' : 'show all'}
        </button>
      </div>
      <form onSubmit={handleAdd} className="flex gap-2 mb-6">
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder="what needs follow-up?"
          className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-[var(--accent)] mono-heading placeholder:text-[var(--text-muted)]" />
        <input value={context} onChange={e => setContext(e.target.value)} placeholder="context"
          className="w-60 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-[var(--accent)] mono-heading placeholder:text-[var(--text-muted)]" />
        <button type="submit" className="px-3 py-2 bg-[var(--accent)] text-[var(--bg-deep)] rounded-lg hover:bg-[#60ccf8]"><Plus size={14} /></button>
      </form>
      <div className="space-y-2">
        {loops.map(l => (
          <div key={l.id} className={`glass-card flex items-start gap-3 p-3 ${l.status !== 'open' ? 'opacity-50' : ''}`}>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm text-[var(--text-primary)]">{l.title}</span>
                {l.status !== 'open' && <span className="mono-heading text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)]">{l.status}</span>}
              </div>
              {l.context && <p className="text-xs text-[var(--text-muted)] mt-1">{l.context}</p>}
              <p className="text-[10px] text-[var(--text-muted)] mt-1">{l.created_at ? new Date(l.created_at).toLocaleDateString() : ''}</p>
            </div>
            {l.status === 'open' && (
              <div className="flex gap-1">
                <button onClick={() => post(`/loops/${l.id}/close`, { status: 'done' }).then(load)}
                  className="text-[var(--green)] hover:text-[#4ade80]" title="Done"><Check size={15} /></button>
                <button onClick={() => post(`/loops/${l.id}/close`, { status: 'dropped' }).then(load)}
                  className="text-[var(--text-muted)] hover:text-[var(--red)]" title="Drop"><X size={15} /></button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
