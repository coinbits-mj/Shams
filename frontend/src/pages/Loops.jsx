import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { Plus, Check, X } from 'lucide-react';

export default function Loops() {
  const [loops, setLoops] = useState([]);
  const [title, setTitle] = useState('');
  const [context, setContext] = useState('');
  const [showAll, setShowAll] = useState(false);

  async function load() {
    const data = await get(`/loops?status=${showAll ? 'all' : 'open'}`);
    if (data) setLoops(data);
  }

  useEffect(() => { load(); }, [showAll]);

  async function handleAdd(e) {
    e.preventDefault();
    if (!title.trim()) return;
    await post('/loops', { title: title.trim(), context: context.trim() });
    setTitle(''); setContext('');
    load();
  }

  async function handleClose(id, status) {
    await post(`/loops/${id}/close`, { status });
    load();
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Open Loops</h2>
        <button onClick={() => setShowAll(!showAll)}
          className="text-xs text-slate-400 hover:text-white px-3 py-1 border border-slate-600 rounded-lg">
          {showAll ? 'Open only' : 'Show all'}
        </button>
      </div>

      <form onSubmit={handleAdd} className="flex gap-2 mb-6">
        <input value={title} onChange={e => setTitle(e.target.value)} placeholder="What needs follow-up?"
          className="flex-1 px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-amber-400" />
        <input value={context} onChange={e => setContext(e.target.value)} placeholder="Context (optional)"
          className="w-64 px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-amber-400" />
        <button type="submit" className="px-3 py-2 bg-amber-500 text-slate-900 rounded-lg hover:bg-amber-400"><Plus size={16} /></button>
      </form>

      <div className="space-y-2">
        {loops.map(l => (
          <div key={l.id} className={`flex items-start gap-3 p-3 rounded-lg border ${
            l.status === 'open' ? 'bg-slate-800 border-slate-700' : 'bg-slate-900 border-slate-800 opacity-60'
          }`}>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-200">{l.title}</span>
                {l.status !== 'open' && <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-400">{l.status}</span>}
              </div>
              {l.context && <p className="text-slate-400 text-xs mt-1">{l.context}</p>}
              <p className="text-slate-600 text-xs mt-1">{l.created_at ? new Date(l.created_at).toLocaleDateString() : ''}</p>
            </div>
            {l.status === 'open' && (
              <div className="flex gap-1">
                <button onClick={() => handleClose(l.id, 'done')} className="text-green-500 hover:text-green-400" title="Done"><Check size={16} /></button>
                <button onClick={() => handleClose(l.id, 'dropped')} className="text-slate-500 hover:text-red-400" title="Drop"><X size={16} /></button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
