import { useState, useEffect } from 'react';
import { get, post, patch } from '../api';
import { Plus, ChevronRight, Target, X, DollarSign } from 'lucide-react';

const stages = ['lead', 'researching', 'evaluating', 'loi', 'due_diligence', 'closing', 'closed'];
const stageLabels = { lead: 'Lead', researching: 'Research', evaluating: 'Eval', loi: 'LOI', due_diligence: 'Diligence', closing: 'Closing', closed: 'Closed' };
const stageColors = { lead: '#64748b', researching: '#38bdf8', evaluating: '#f59e0b', loi: '#a855f7', due_diligence: '#06b6d4', closing: '#22c55e', closed: '#22c55e' };
const agentColors = { shams: '#f59e0b', rumi: '#06b6d4', wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6' };

const fmt = n => n == null || n === 0 ? '' : '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });

export default function Deals() {
  const [deals, setDeals] = useState([]);
  const [selected, setSelected] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [newDeal, setNewDeal] = useState({ title: '', deal_type: 'acquisition', value: '', location: '', notes: '' });

  async function load() {
    const d = await get('/deals');
    if (d) setDeals(d);
  }
  useEffect(() => { load(); }, []);

  async function moveDeal(id, stage) {
    await patch(`/deals/${id}`, { stage });
    load();
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!newDeal.title.trim()) return;
    await post('/deals', { ...newDeal, value: parseFloat(newDeal.value) || 0 });
    setNewDeal({ title: '', deal_type: 'acquisition', value: '', location: '', notes: '' });
    setShowNew(false);
    load();
  }

  const dealsByStage = {};
  stages.forEach(s => { dealsByStage[s] = deals.filter(d => d.stage === s); });

  const totalPipeline = deals.filter(d => !['closed', 'dead'].includes(d.stage)).reduce((sum, d) => sum + (d.value || 0), 0);

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-[var(--border)] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="mono-heading text-lg text-[var(--text-primary)]">deal pipeline</h2>
          {totalPipeline > 0 && (
            <span className="text-xs text-[var(--text-muted)]">
              pipeline: <span className="text-[#22c55e] mono-heading">{fmt(totalPipeline)}</span>
            </span>
          )}
        </div>
        <button onClick={() => setShowNew(true)}
          className="text-xs px-3 py-1.5 rounded-lg bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)] hover:bg-[var(--accent)] hover:text-[var(--bg-deep)] transition-colors mono-heading flex items-center gap-1.5">
          <Plus size={12} /> add deal
        </button>
      </div>

      {/* Pipeline columns */}
      <div className="flex-1 overflow-x-auto p-4">
        <div className="flex gap-3 min-w-max h-full">
          {stages.map(stage => (
            <div key={stage} className="w-56 flex flex-col">
              <div className="flex items-center justify-between px-2 py-2 mb-2">
                <span className="mono-heading text-[11px] uppercase tracking-wider" style={{ color: stageColors[stage] }}>{stageLabels[stage]}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-card)] text-[var(--text-muted)]">
                  {dealsByStage[stage].length}
                </span>
              </div>
              <div className="flex-1 space-y-2 overflow-y-auto">
                {dealsByStage[stage].map(d => (
                  <div key={d.id} className="glass-card p-3 group cursor-pointer" onClick={() => setSelected(d)}>
                    {d.score > 0 && (
                      <div className="flex items-center gap-1 mb-1">
                        <div className="flex">
                          {[...Array(Math.min(d.score, 10))].map((_, i) => (
                            <div key={i} className="w-1.5 h-1.5 rounded-full mr-0.5"
                              style={{ backgroundColor: d.score >= 8 ? '#22c55e' : d.score >= 5 ? '#f59e0b' : '#64748b' }} />
                          ))}
                        </div>
                        <span className="text-[10px] text-[var(--text-muted)]">{d.score}/10</span>
                      </div>
                    )}
                    <p className="text-sm text-[var(--text-primary)] mb-1">{d.title}</p>
                    {d.value > 0 && <p className="text-xs text-[#22c55e] mono-heading mb-1">{fmt(d.value)}</p>}
                    {d.location && <p className="text-[10px] text-[var(--text-muted)] mb-1">{d.location}</p>}
                    {d.next_action && <p className="text-[10px] text-[var(--text-secondary)] line-clamp-1">{d.next_action}</p>}
                    {d.deadline && (
                      <p className="text-[10px] text-[var(--text-muted)] mt-1">due: {new Date(d.deadline).toLocaleDateString()}</p>
                    )}
                    {/* Move button on hover */}
                    {stage !== 'closed' && (
                      <div className="mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onClick={e => { e.stopPropagation(); moveDeal(d.id, stages[stages.indexOf(stage) + 1]); }}
                          className="text-[10px] px-2 py-0.5 rounded bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)] hover:bg-[var(--accent)] hover:text-[var(--bg-deep)] transition-colors">
                          {stageLabels[stages[stages.indexOf(stage) + 1]]} <ChevronRight size={10} className="inline" />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* New deal modal */}
      {showNew && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={() => setShowNew(false)}>
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="mono-heading text-sm text-[var(--text-primary)]">new deal</h3>
              <button onClick={() => setShowNew(false)} className="text-[var(--text-muted)]"><X size={16} /></button>
            </div>
            <form onSubmit={handleCreate} className="space-y-3">
              <input value={newDeal.title} onChange={e => setNewDeal(p => ({ ...p, title: e.target.value }))}
                placeholder="deal title" className="w-full px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] mono-heading placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]" />
              <div className="grid grid-cols-2 gap-3">
                <select value={newDeal.deal_type} onChange={e => setNewDeal(p => ({ ...p, deal_type: e.target.value }))}
                  className="px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-secondary)]">
                  <option value="acquisition">Acquisition</option>
                  <option value="real_estate">Real Estate</option>
                  <option value="partnership">Partnership</option>
                  <option value="investment">Investment</option>
                  <option value="vendor">Vendor</option>
                  <option value="other">Other</option>
                </select>
                <input value={newDeal.value} onChange={e => setNewDeal(p => ({ ...p, value: e.target.value }))}
                  placeholder="value ($)" type="number" className="px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] mono-heading placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]" />
              </div>
              <input value={newDeal.location} onChange={e => setNewDeal(p => ({ ...p, location: e.target.value }))}
                placeholder="location" className="w-full px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] mono-heading placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]" />
              <textarea value={newDeal.notes} onChange={e => setNewDeal(p => ({ ...p, notes: e.target.value }))}
                placeholder="notes" rows={2} className="w-full px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] mono-heading placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] resize-none" />
              <button type="submit"
                className="w-full py-2 rounded-lg bg-[var(--accent)] text-[var(--bg-deep)] mono-heading text-sm hover:bg-[#60ccf8] transition-colors">
                add to pipeline
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Deal detail modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={() => setSelected(null)}>
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl max-w-lg w-full p-5" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <span className="text-[10px] px-1.5 py-0.5 rounded mono-heading uppercase" style={{ color: stageColors[selected.stage], backgroundColor: `${stageColors[selected.stage]}15` }}>{stageLabels[selected.stage]}</span>
                <h3 className="text-lg text-[var(--text-primary)] mt-1">{selected.title}</h3>
              </div>
              <button onClick={() => setSelected(null)} className="text-[var(--text-muted)]"><X size={16} /></button>
            </div>
            <div className="space-y-3">
              {selected.value > 0 && <p className="text-xl text-[#22c55e] mono-heading">{fmt(selected.value)}</p>}
              {selected.score > 0 && <p className="text-xs text-[var(--text-muted)]">Score: {selected.score}/10</p>}
              {selected.deal_type && <p className="text-xs text-[var(--text-muted)]">Type: {selected.deal_type}</p>}
              {selected.contact && <p className="text-xs text-[var(--text-secondary)]">Contact: {selected.contact}</p>}
              {selected.location && <p className="text-xs text-[var(--text-secondary)]">Location: {selected.location}</p>}
              {selected.source && <p className="text-xs text-[var(--text-muted)]">Source: {selected.source}</p>}
              {selected.next_action && (
                <div className="p-3 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)]">
                  <span className="text-[10px] text-[var(--text-muted)] mono-heading">next action</span>
                  <p className="text-xs text-[var(--text-primary)] mt-1">{selected.next_action}</p>
                </div>
              )}
              {selected.notes && <p className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap">{selected.notes}</p>}
              {selected.deadline && <p className="text-[10px] text-[var(--text-muted)]">Deadline: {new Date(selected.deadline).toLocaleDateString()}</p>}
              <div className="flex gap-2 pt-2">
                {selected.stage !== 'closed' && selected.stage !== 'dead' && (
                  <>
                    <button onClick={() => { moveDeal(selected.id, stages[stages.indexOf(selected.stage) + 1]); setSelected(null); }}
                      className="text-xs px-3 py-1.5 rounded-lg bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)] mono-heading">
                      advance to {stageLabels[stages[stages.indexOf(selected.stage) + 1]]}
                    </button>
                    <button onClick={() => { moveDeal(selected.id, 'dead'); setSelected(null); }}
                      className="text-xs px-3 py-1.5 rounded-lg bg-[#ef444420] text-[#ef4444] border border-[#ef444430] mono-heading">
                      kill deal
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
