import { useState, useEffect } from 'react';
import { get, post, del } from '../api';
import { Plus, Trash2 } from 'lucide-react';

export default function Memory() {
  const [memories, setMemories] = useState({});
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');

  async function load() {
    const data = await get('/memory');
    if (data) setMemories(data);
  }

  useEffect(() => { load(); }, []);

  async function handleAdd(e) {
    e.preventDefault();
    if (!key.trim() || !value.trim()) return;
    await post('/memory', { key: key.trim(), value: value.trim() });
    setKey(''); setValue('');
    load();
  }

  async function handleDelete(k) {
    await del(`/memory/${encodeURIComponent(k)}`);
    load();
  }

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold mb-4">Persistent Memory</h2>

      <form onSubmit={handleAdd} className="flex gap-2 mb-6">
        <input value={key} onChange={e => setKey(e.target.value)} placeholder="Key"
          className="px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm w-48 focus:outline-none focus:border-amber-400" />
        <input value={value} onChange={e => setValue(e.target.value)} placeholder="Value"
          className="flex-1 px-3 py-2 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:border-amber-400" />
        <button type="submit" className="px-3 py-2 bg-amber-500 text-slate-900 rounded-lg hover:bg-amber-400"><Plus size={16} /></button>
      </form>

      <div className="space-y-2">
        {Object.entries(memories).map(([k, v]) => (
          <div key={k} className="flex items-start gap-3 p-3 bg-slate-800 rounded-lg border border-slate-700">
            <div className="flex-1">
              <span className="text-amber-400 text-sm font-medium">{k}</span>
              <p className="text-slate-300 text-sm mt-1">{v}</p>
            </div>
            <button onClick={() => handleDelete(k)} className="text-slate-500 hover:text-red-400 mt-1"><Trash2 size={14} /></button>
          </div>
        ))}
        {Object.keys(memories).length === 0 && <p className="text-slate-500 text-sm">No memories stored yet.</p>}
      </div>
    </div>
  );
}
