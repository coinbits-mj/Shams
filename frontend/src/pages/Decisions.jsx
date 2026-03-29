import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { Plus } from 'lucide-react';

export default function Decisions() {
  const [decisions, setDecisions] = useState([]);
  const [summary, setSummary] = useState('');
  const [reasoning, setReasoning] = useState('');

  async function load() { const d = await get('/decisions?limit=50'); if (d) setDecisions(d); }
  useEffect(() => { load(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    if (!summary.trim()) return;
    await post('/decisions', { summary: summary.trim(), reasoning: reasoning.trim() });
    setSummary(''); setReasoning(''); load();
  }

  return (
    <div className="p-6">
      <h2 className="mono-heading text-lg mb-4">decision log</h2>
      <form onSubmit={handleAdd} className="flex gap-2 mb-6">
        <input value={summary} onChange={e => setSummary(e.target.value)} placeholder="what was decided?"
          className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-[var(--accent)] mono-heading placeholder:text-[var(--text-muted)]" />
        <input value={reasoning} onChange={e => setReasoning(e.target.value)} placeholder="why?"
          className="w-60 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm focus:outline-none focus:border-[var(--accent)] mono-heading placeholder:text-[var(--text-muted)]" />
        <button type="submit" className="px-3 py-2 bg-[var(--accent)] text-[var(--bg-deep)] rounded-lg hover:bg-[#60ccf8]"><Plus size={14} /></button>
      </form>
      <div className="space-y-2">
        {decisions.map((d, i) => (
          <div key={i} className="glass-card p-3">
            <p className="text-sm text-[var(--text-primary)]">{d.summary}</p>
            {d.reasoning && <p className="text-xs text-[var(--text-muted)] mt-1">{d.reasoning}</p>}
            {d.outcome && <p className="text-xs text-[var(--amber)] mt-1">outcome: {d.outcome}</p>}
            <p className="text-[10px] text-[var(--text-muted)] mt-1">{d.created_at ? new Date(d.created_at).toLocaleDateString() : ''}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
