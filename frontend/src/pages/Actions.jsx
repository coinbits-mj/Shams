import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { CheckCircle, XCircle, Clock, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';

const agentColors = {
  shams: '#f59e0b', rumi: '#06b6d4', leo: '#22c55e',
  wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6',
};

const statusConfig = {
  pending: { color: '#f59e0b', label: 'pending', icon: Clock },
  approved: { color: '#22c55e', label: 'approved', icon: CheckCircle },
  rejected: { color: '#ef4444', label: 'rejected', icon: XCircle },
  executing: { color: '#38bdf8', label: 'executing', icon: Clock },
  completed: { color: '#22c55e', label: 'completed', icon: CheckCircle },
  failed: { color: '#ef4444', label: 'failed', icon: AlertTriangle },
};

export default function Actions() {
  const [actions, setActions] = useState([]);
  const [filter, setFilter] = useState('pending');
  const [expanded, setExpanded] = useState(null);

  async function load() {
    const params = filter ? `?status=${filter}` : '';
    const data = await get(`/actions${params}`);
    if (data) setActions(data);
  }

  useEffect(() => { load(); const i = setInterval(load, 10000); return () => clearInterval(i); }, [filter]);

  async function approve(id) {
    await post(`/actions/${id}/approve`);
    load();
  }

  async function reject(id) {
    await post(`/actions/${id}/reject`, {});
    load();
  }

  async function executeAction(id) {
    await post(`/actions/${id}/execute`);
    load();
  }

  async function batchApprove() {
    const ids = actions.filter(a => a.status === 'pending').map(a => a.id);
    if (ids.length === 0) return;
    await post('/actions/batch-approve', { ids });
    load();
  }

  // Group pending actions by agent
  const grouped = {};
  actions.forEach(a => {
    const key = a.agent_name;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(a);
  });

  const pendingCount = actions.filter(a => a.status === 'pending').length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-[var(--border)] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <h2 className="mono-heading text-lg text-[var(--text-primary)]">actions</h2>
          {pendingCount > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-[#f59e0b20] text-[#f59e0b] mono-heading">
              {pendingCount} pending
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {filter === 'pending' && pendingCount > 1 && (
            <button onClick={batchApprove}
              className="text-xs px-3 py-1.5 rounded-lg bg-[#22c55e20] text-[#22c55e] border border-[#22c55e30] hover:bg-[#22c55e30] transition-colors mono-heading">
              approve all ({pendingCount})
            </button>
          )}
          <div className="flex rounded-lg border border-[var(--border)] overflow-hidden">
            {['pending', 'approved', 'completed', 'rejected', ''].map(s => (
              <button key={s} onClick={() => setFilter(s)}
                className={`px-3 py-1.5 text-xs mono-heading transition-colors ${
                  filter === s
                    ? 'bg-[var(--accent-glow)] text-[var(--accent)] border-r border-[var(--border)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] border-r border-[var(--border)]'
                }`}>
                {s || 'all'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Actions list */}
      <div className="flex-1 overflow-y-auto p-6">
        {Object.keys(grouped).length === 0 && (
          <div className="text-center py-16">
            <p className="text-[var(--text-muted)] text-sm">no {filter || ''} actions</p>
          </div>
        )}

        {Object.entries(grouped).map(([agent, agentActions]) => (
          <div key={agent} className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: agentColors[agent] || '#64748b' }} />
              <span className="mono-heading text-sm" style={{ color: agentColors[agent] || '#64748b' }}>{agent}</span>
              <span className="text-[10px] text-[var(--text-muted)]">{agentActions.length} action{agentActions.length !== 1 ? 's' : ''}</span>
            </div>

            <div className="space-y-2">
              {agentActions.map(action => {
                const sc = statusConfig[action.status] || statusConfig.pending;
                const StatusIcon = sc.icon;
                const isExpanded = expanded === action.id;

                return (
                  <div key={action.id} className="glass-card p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <StatusIcon size={14} style={{ color: sc.color }} />
                          <span className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wider mono-heading"
                            style={{ color: sc.color, backgroundColor: `${sc.color}15` }}>
                            {action.action_type.replace('_', ' ')}
                          </span>
                          <span className="text-[10px] text-[var(--text-muted)]">#{action.id}</span>
                        </div>
                        <p className="text-sm text-[var(--text-primary)] mb-1">{action.title}</p>
                        {action.description && !isExpanded && (
                          <p className="text-xs text-[var(--text-muted)] line-clamp-1">{action.description}</p>
                        )}
                        {isExpanded && (
                          <div className="mt-2 space-y-2">
                            {action.description && (
                              <p className="text-xs text-[var(--text-secondary)]">{action.description}</p>
                            )}
                            {action.payload && Object.keys(action.payload).length > 0 && (
                              <pre className="text-[10px] text-[var(--text-muted)] bg-[var(--bg-deep)] p-2 rounded overflow-x-auto">
                                {JSON.stringify(action.payload, null, 2)}
                              </pre>
                            )}
                            {action.result && (
                              <div className="text-xs text-[var(--text-secondary)]">
                                <span className="text-[var(--text-muted)]">Result: </span>{action.result}
                              </div>
                            )}
                          </div>
                        )}
                        <div className="flex items-center gap-3 mt-2">
                          <span className="text-[10px] text-[var(--text-muted)]">
                            {action.created_at ? new Date(action.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                          </span>
                          {action.mission_id && (
                            <span className="text-[10px] text-[var(--text-muted)]">mission #{action.mission_id}</span>
                          )}
                          <button onClick={() => setExpanded(isExpanded ? null : action.id)}
                            className="text-[10px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] flex items-center gap-0.5">
                            {isExpanded ? <><ChevronUp size={10} /> less</> : <><ChevronDown size={10} /> more</>}
                          </button>
                        </div>
                      </div>

                      <div className="flex gap-2 ml-4 flex-shrink-0">
                        {action.status === 'pending' && (
                          <>
                            <button onClick={() => approve(action.id)}
                              className="text-xs px-3 py-1.5 rounded-lg bg-[#22c55e20] text-[#22c55e] border border-[#22c55e30] hover:bg-[#22c55e30] transition-colors mono-heading">
                              approve
                            </button>
                            <button onClick={() => reject(action.id)}
                              className="text-xs px-3 py-1.5 rounded-lg bg-[#ef444420] text-[#ef4444] border border-[#ef444430] hover:bg-[#ef444430] transition-colors mono-heading">
                              reject
                            </button>
                          </>
                        )}
                        {action.status === 'approved' && action.action_type === 'create_pr' && (
                          <button onClick={() => executeAction(action.id)}
                            className="text-xs px-3 py-1.5 rounded-lg bg-[#3b82f620] text-[#3b82f6] border border-[#3b82f630] hover:bg-[#3b82f630] transition-colors mono-heading">
                            execute PR
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
