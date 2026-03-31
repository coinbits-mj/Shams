import { useState, useEffect } from 'react';
import { get, post, patch } from '../api';
import { Plus, Sun, Activity, Heart, Search, Zap, ChevronRight, X } from 'lucide-react';

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
  const [feedAgent, setFeedAgent] = useState('');
  const [feedType, setFeedType] = useState('');
  const [selectedMission, setSelectedMission] = useState(null);
  const [selectedAgent, setSelectedAgent] = useState(null);

  async function load() {
    const feedParams = new URLSearchParams({ limit: '30' });
    if (feedAgent) feedParams.set('agent', feedAgent);
    if (feedType) feedParams.set('event_type', feedType);
    const [a, m, f] = await Promise.all([get('/agents'), get('/missions'), get(`/feed?${feedParams}`)]);
    if (a) setAgents(a);
    if (m) setMissions(m);
    if (f) setFeed(f);
  }

  useEffect(() => { load(); const i = setInterval(load, 15000); return () => clearInterval(i); }, [feedAgent, feedType]);

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

  async function openAgent(name) {
    const data = await get(`/agents/${name}`);
    if (data) setSelectedAgent(data);
  }

  async function openMission(id) {
    const data = await get(`/missions/${id}`);
    if (data) setSelectedMission(data);
  }

  async function updateMissionAgent(id, agent) {
    await patch(`/missions/${id}`, { assigned_agent: agent || null });
    openMission(id);
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
              <div key={agent.name} className="glass-card px-4 py-2.5 flex items-center gap-3 min-w-[160px] cursor-pointer hover:border-[var(--border-bright)] transition-colors" onClick={() => openAgent(agent.name)}>
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
                    <div key={m.id} className="glass-card p-3 group cursor-pointer" onClick={() => openMission(m.id)}>
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
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full bg-[var(--green)] pulse-active" />
            <span className="mono-heading text-sm text-[var(--text-primary)]">live feed</span>
          </div>
          <div className="flex gap-1 flex-wrap">
            {['', 'tool_call', 'action_proposed', 'action_approved', 'mission_update', 'group_chat', 'briefing', 'error'].map(t => (
              <button key={t} onClick={() => setFeedType(t)}
                className={`text-[10px] px-1.5 py-0.5 rounded mono-heading transition-colors ${
                  feedType === t ? 'bg-[var(--accent-glow)] text-[var(--accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
                }`}>
                {t || 'all'}
              </button>
            ))}
          </div>
          <div className="flex gap-1 mt-1 flex-wrap">
            <button onClick={() => setFeedAgent('')}
              className={`text-[10px] px-1.5 py-0.5 rounded mono-heading ${!feedAgent ? 'bg-[var(--accent-glow)] text-[var(--accent)]' : 'text-[var(--text-muted)]'}`}>all</button>
            {agents.map(a => (
              <button key={a.name} onClick={() => setFeedAgent(a.name)}
                className={`text-[10px] px-1.5 py-0.5 rounded mono-heading ${feedAgent === a.name ? 'bg-[var(--accent-glow)]' : ''}`}
                style={{ color: feedAgent === a.name ? (a.config?.color || '#f59e0b') : undefined }}>
                {a.name}
              </button>
            ))}
          </div>
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

      {/* Agent detail modal */}
      {selectedAgent && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={() => setSelectedAgent(null)}>
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between p-5 border-b border-[var(--border)]">
              <div className="flex items-center gap-3">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: selectedAgent.config?.color || statusColors[selectedAgent.status] }} />
                <div>
                  <h3 className="text-lg text-[var(--text-primary)] mono-heading">{selectedAgent.name}</h3>
                  <p className="text-xs text-[var(--text-muted)]">{selectedAgent.role}</p>
                </div>
                <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase`}
                  style={{ color: statusColors[selectedAgent.status], backgroundColor: `${statusColors[selectedAgent.status]}15` }}>
                  {selectedAgent.status}
                </span>
              </div>
              <button onClick={() => setSelectedAgent(null)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
                <X size={18} />
              </button>
            </div>

            <div className="p-5 space-y-5">
              {/* Trust */}
              {selectedAgent.trust && (
                <div className="glass-card p-4">
                  <span className="text-xs text-[var(--text-muted)] mono-heading">trust score</span>
                  <div className="grid grid-cols-4 gap-3 mt-2 text-center">
                    <div>
                      <p className="text-lg text-[var(--text-primary)] mono-heading">{selectedAgent.trust.total_proposed}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">proposed</p>
                    </div>
                    <div>
                      <p className="text-lg text-[#22c55e] mono-heading">{selectedAgent.trust.total_approved}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">approved</p>
                    </div>
                    <div>
                      <p className="text-lg text-[#ef4444] mono-heading">{selectedAgent.trust.total_rejected}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">rejected</p>
                    </div>
                    <div>
                      <p className="text-lg mono-heading" style={{
                        color: selectedAgent.trust.approval_rate >= 90 ? '#22c55e' : selectedAgent.trust.approval_rate >= 70 ? '#f59e0b' : '#ef4444'
                      }}>{selectedAgent.trust.approval_rate}%</p>
                      <p className="text-[10px] text-[var(--text-muted)]">rate</p>
                    </div>
                  </div>
                  <div className="mt-2 text-[10px] text-[var(--text-muted)]">
                    auto-approve: {selectedAgent.trust.auto_approve ? '✓ enabled' : '✗ disabled'}
                  </div>
                </div>
              )}

              {/* Missions */}
              {selectedAgent.missions?.length > 0 && (
                <div>
                  <span className="text-xs text-[var(--text-muted)] mono-heading">missions ({selectedAgent.missions.length})</span>
                  <div className="mt-1 space-y-1">
                    {selectedAgent.missions.map(m => (
                      <div key={m.id} className="flex items-center justify-between p-2 rounded bg-[var(--bg-card)] border border-[var(--border)] cursor-pointer hover:border-[var(--border-bright)]"
                        onClick={() => { setSelectedAgent(null); openMission(m.id); }}>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] px-1 rounded" style={{ color: priorityColors[m.priority], backgroundColor: `${priorityColors[m.priority]}15` }}>{m.priority}</span>
                          <span className="text-xs text-[var(--text-primary)]">{m.title}</span>
                        </div>
                        <span className="text-[10px] text-[var(--text-muted)]">{m.status}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent actions */}
              {selectedAgent.actions?.length > 0 && (
                <div>
                  <span className="text-xs text-[var(--text-muted)] mono-heading">recent actions ({selectedAgent.actions.length})</span>
                  <div className="mt-1 space-y-1">
                    {selectedAgent.actions.slice(0, 10).map(a => (
                      <div key={a.id} className="flex items-center justify-between p-2 rounded bg-[var(--bg-card)] border border-[var(--border)]">
                        <div>
                          <span className="text-xs text-[var(--text-primary)]">{a.title}</span>
                          <span className="text-[10px] ml-2 text-[var(--text-muted)]">{a.action_type}</span>
                        </div>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          a.status === 'completed' || a.status === 'approved' ? 'text-[#22c55e]' :
                          a.status === 'rejected' || a.status === 'failed' ? 'text-[#ef4444]' : 'text-[#f59e0b]'
                        }`}>{a.status}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Activity */}
              {selectedAgent.activity?.length > 0 && (
                <div>
                  <span className="text-xs text-[var(--text-muted)] mono-heading">recent activity</span>
                  <div className="mt-1 space-y-1 border-l-2 border-[var(--border)] ml-2 pl-3 max-h-48 overflow-y-auto">
                    {selectedAgent.activity.slice(0, 15).map((a, i) => (
                      <div key={i} className="py-0.5">
                        <span className="text-[10px] text-[var(--text-muted)]">
                          {a.timestamp ? new Date(a.timestamp).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                        </span>
                        <p className="text-xs text-[var(--text-secondary)]">{a.content}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Mission detail modal */}
      {selectedMission && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={() => setSelectedMission(null)}>
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between p-5 border-b border-[var(--border)]">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wider"
                    style={{ color: priorityColors[selectedMission.priority], backgroundColor: `${priorityColors[selectedMission.priority]}15` }}>
                    {selectedMission.priority}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)] uppercase">{selectedMission.status}</span>
                  <span className="text-[10px] text-[var(--text-muted)]">#{selectedMission.id}</span>
                </div>
                <h3 className="text-lg text-[var(--text-primary)]">{selectedMission.title}</h3>
              </div>
              <button onClick={() => setSelectedMission(null)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
                <X size={18} />
              </button>
            </div>

            <div className="p-5 space-y-4">
              {selectedMission.description && (
                <p className="text-sm text-[var(--text-secondary)]">{selectedMission.description}</p>
              )}

              {/* Assigned agent */}
              <div className="flex items-center gap-3">
                <span className="text-xs text-[var(--text-muted)]">assigned to:</span>
                <select
                  value={selectedMission.assigned_agent || ''}
                  onChange={e => updateMissionAgent(selectedMission.id, e.target.value)}
                  className="text-xs px-2 py-1 bg-[var(--bg-card)] border border-[var(--border)] rounded text-[var(--text-primary)]"
                >
                  <option value="">unassigned</option>
                  {agents.map(a => <option key={a.name} value={a.name}>{a.name}</option>)}
                </select>
              </div>

              {selectedMission.result && (
                <div>
                  <span className="text-xs text-[var(--text-muted)] mono-heading">result</span>
                  <p className="text-sm text-[var(--text-primary)] mt-1 bg-[var(--bg-card)] p-3 rounded-lg border border-[var(--border)]">{selectedMission.result}</p>
                </div>
              )}

              {/* Actions */}
              {selectedMission.actions?.length > 0 && (
                <div>
                  <span className="text-xs text-[var(--text-muted)] mono-heading">actions ({selectedMission.actions.length})</span>
                  <div className="mt-1 space-y-1.5">
                    {selectedMission.actions.map(a => (
                      <div key={a.id} className="flex items-center justify-between p-2 rounded bg-[var(--bg-card)] border border-[var(--border)]">
                        <div>
                          <span className="text-xs text-[var(--text-primary)]">{a.title}</span>
                          <span className="text-[10px] ml-2 text-[var(--text-muted)]">{a.action_type}</span>
                        </div>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase ${
                          a.status === 'completed' || a.status === 'approved' ? 'text-[#22c55e] bg-[#22c55e15]' :
                          a.status === 'rejected' || a.status === 'failed' ? 'text-[#ef4444] bg-[#ef444415]' :
                          'text-[#f59e0b] bg-[#f59e0b15]'
                        }`}>{a.status}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Timeline */}
              {selectedMission.activity?.length > 0 && (
                <div>
                  <span className="text-xs text-[var(--text-muted)] mono-heading">timeline</span>
                  <div className="mt-1 space-y-1 border-l-2 border-[var(--border)] ml-2 pl-3">
                    {selectedMission.activity.map((a, i) => (
                      <div key={i} className="py-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-[var(--text-muted)]">
                            {a.timestamp ? new Date(a.timestamp).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                          </span>
                          <span className="text-[10px] mono-heading" style={{ color: agents.find(ag => ag.name === a.agent_name)?.config?.color || '#64748b' }}>{a.agent_name}</span>
                        </div>
                        <p className="text-xs text-[var(--text-secondary)]">{a.content}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="text-[10px] text-[var(--text-muted)]">
                created {selectedMission.created_at ? new Date(selectedMission.created_at).toLocaleString() : ''}
                {selectedMission.updated_at && selectedMission.updated_at !== selectedMission.created_at &&
                  ` \u00b7 updated ${new Date(selectedMission.updated_at).toLocaleString()}`}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
