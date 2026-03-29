import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { Plus } from 'lucide-react';

export default function Decisions() {
  const [decisions, setDecisions] = useState([]);
  const [summary, setSummary] = useState('');
  const [reasoning, setReasoning] = useState('');

  async function load() {
    const data = await get('/decisions?limit=50');
    if (data) setDecisions(data);
  }

  useEffect(() => { load(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    if (!summary.trim()) return;
    await post('/decisions', { summary: summary.trim(), reasoning: reasoning.trim() });
    setSummary(''); setReasoning('');
    load();
  }

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold mb-4">Decision Log</h2>

      <form onSubmit={handleAdd} className="flex gap-2 mb-6">
        <input value={summary} onChange={e => setSummary(e.target.value)} placeholder="What was decided?"
          className="flex-1 px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-amber-400" />
        <input value={reasoning} onChange={e => setReasoning(e.target.value)} placeholder="Why? (optional)"
          className="w-64 px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-amber-400" />
        <button type="submit" className="px-3 py-2 bg-amber-500 text-slate-900 rounded-lg hover:bg-amber-400"><Plus size={16} /></button>
      </form>

      <div className="space-y-2">
        {decisions.map((d, i) => (
          <div key={i} className="p-3 bg-slate-800 rounded-lg border border-slate-700">
            <p className="text-sm text-slate-200 font-medium">{d.summary}</p>
            {d.reasoning && <p className="text-xs text-slate-400 mt-1">{d.reasoning}</p>}
            {d.outcome && <p className="text-xs text-amber-400/70 mt-1">Outcome: {d.outcome}</p>}
            <p className="text-xs text-slate-600 mt-1">{d.created_at ? new Date(d.created_at).toLocaleDateString() : ''}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
