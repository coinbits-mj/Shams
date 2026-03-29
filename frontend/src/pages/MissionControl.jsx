import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { Plus, Sun, Activity, Heart, Search, Zap, ChevronRight } from 'lucide-react';

const agentIcons = { shams: Sun, rumi: Activity, leo: Heart };
const statusColors = { active: '#22c55e', idle: '#f59e0b', offline: '#475569', error: '#ef4444' };
const priorityColors = { urgent: '#ef4444', high: '#f97316', normal: '#38bdf8', low: '#64748b' };
const columns = ['inbox', 'assigned', 'active', 'review', 'done'];

export default function MissionControl() {
  const [agents, setAgents] = useState([]);
  const [missions, setMissions] = useState([]);
  const [feed, setFeed] = useState([]);
  const [newTitle, setNewTitle] = useState('');
  const [newPriority, setNewPriority] = useState('normal');

  async function load() {
    const [a, m, f] = await Promise.all([get('/agents'), get('/missions'), get('/feed?limit=30')]);
    if (a) setAgents(a);
    if (m) setMissions(m);
    if (f) setFeed(f);
  }

  useEffect(() => { load(); const i = setInterval(load, 15000); return () => clearInterval(i); }, []);

  async function handleNewMission(e) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    await post('/missions', { title: newTitle.trim(), priority: newPriority });
    setNewTitle('');
    load();
  }

  async function moveMission(id, status) {
    await post(`/missions/${id}`, { status });
    load();
  }

  const missionsByStatus = {};
  columns.forEach(c => { missionsByStatus[c] = missions.filter(m => m.status === c); });

  return (
    <div className="flex h-full">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="border-b border-[var(--border)] px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <h2 className="mono-heading text-lg text-[var(--text-primary)]">mission queue</h2>
            <div className="flex gap-3 text-xs">
              <span className="text-[var(--text-muted)]">
                <span className="text-[var(--accent)]">{agents.filter(a => a.status === 'active').length}</span> agents active
              </span>
              <span className="text-[var(--text-muted)]">
                <span className="text-[var(--text-primary)]">{missions.filter(m => m.status !== 'done' && m.status !== 'dropped').length}</span> tasks open
              </span>
            </div>
          </div>
          <form onSubmit={handleNewMission} className="flex gap-2">
            <input value={newTitle} onChange={e => setNewTitle(e.target.value)}
              placeholder="+ new mission"
              className="px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm w-60 focus:outline-none focus:border-[var(--accent)] mono-heading placeholder:text-[var(--text-muted)]" />
            <select value={newPriority} onChange={e => setNewPriority(e.target.value)}
              className="px-2 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-secondary)] text-xs">
              <option value="urgent">urgent</option>
              <option value="high">high</option>
              <option value="normal">normal</option>
              <option value="low">low</option>
            </select>
          </form>
        </div>

        {/* Agents bar */}
        <div className="border-b border-[var(--border)] px-6 py-3 flex gap-4">
          {agents.map(agent => {
            const Icon = agentIcons[agent.name] || Zap;
            const color = statusColors[agent.status] || '#475569';
            return (
              <div key={agent.name} className="glass-card px-4 py-2.5 flex items-center gap-3 min-w-[160px]">
                <div className="relative">
                  <Icon size={18} style={{ color: agent.config?.color || color }} />
                  <div className={`absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full ${agent.status === 'active' ? 'pulse-active' : ''}`}
                    style={{ backgroundColor: color }} />
                </div>
                <div>
                  <p className="mono-heading text-sm text-[var(--text-primary)]">{agent.name}</p>
                  <p className="text-[10px] text-[var(--text-muted)]">{agent.role}</p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Kanban board */}
        <div className="flex-1 overflow-x-auto p-4">
          <div className="flex gap-3 min-w-max h-full">
            {columns.map(col => (
              <div key={col} className="w-72 flex flex-col">
                <div className="flex items-center justify-between px-2 py-2 mb-2">
                  <span className="mono-heading text-xs text-[var(--text-muted)] uppercase tracking-wider">{col}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-card)] text-[var(--text-muted)]">
                    {missionsByStatus[col]?.length || 0}
                  </span>
                </div>
                <div className="flex-1 space-y-2 overflow-y-auto">
                  {(missionsByStatus[col] || []).map(m => (
                    <div key={m.id} className="glass-card p-3 group cursor-pointer">
                      <div className="flex items-start justify-between mb-1.5">
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wider"
                          style={{ color: priorityColors[m.priority], backgroundColor: `${priorityColors[m.priority]}15` }}>
                          {m.priority}
                        </span>
                        {m.assigned_agent && (
                          <span className="text-[10px] text-[var(--text-muted)]">{m.assigned_agent}</span>
                        )}
                      </div>
                      <p className="text-sm text-[var(--text-primary)] mb-1">{m.title}</p>
                      {m.description && <p className="text-xs text-[var(--text-muted)] mb-2 line-clamp-2">{m.description}</p>}
                      {m.tags?.length > 0 && (
                        <div className="flex gap-1 flex-wrap mb-2">
                          {m.tags.map((t, i) => (
                            <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)]">{t}</span>
                          ))}
                        </div>
                      )}
                      {/* Move buttons */}
                      <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        {col !== 'done' && (
                          <button onClick={() => moveMission(m.id, columns[columns.indexOf(col) + 1])}
                            className="text-[10px] px-2 py-0.5 rounded bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)] hover:bg-[var(--accent)] hover:text-[var(--bg-deep)] transition-colors">
                            {columns[columns.indexOf(col) + 1]} <ChevronRight size={10} className="inline" />
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Live feed sidebar */}
      <div className="w-80 border-l border-[var(--border)] bg-[var(--bg-surface)] flex flex-col">
        <div className="px-4 py-3 border-b border-[var(--border)] flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[var(--green)] pulse-active" />
          <span className="mono-heading text-sm text-[var(--text-primary)]">live feed</span>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {feed.map((f, i) => {
            const agentColor = agents.find(a => a.name === f.agent_name)?.config?.color || '#64748b';
            return (
              <div key={i} className="p-2.5 rounded-lg bg-[var(--bg-card)] border border-[var(--border)]">
                <div className="flex items-center gap-2 mb-1">
                  <span className="mono-heading text-xs font-medium" style={{ color: agentColor }}>{f.agent_name}</span>
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {f.timestamp ? new Date(f.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                  </span>
                </div>
                <p className="text-xs text-[var(--text-secondary)]">{f.content}</p>
              </div>
            );
          })}
          {feed.length === 0 && (
            <p className="text-xs text-[var(--text-muted)] text-center py-8">no activity yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
