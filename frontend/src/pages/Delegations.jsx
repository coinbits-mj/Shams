import { useState, useEffect } from 'react';
import { get } from '../api';
import { useNavigate } from 'react-router-dom';
import { LayoutGrid, ShieldCheck, Workflow, CheckCircle, Clock, AlertTriangle } from 'lucide-react';

const agentColors = {
  shams: '#f59e0b', rumi: '#06b6d4', leo: '#22c55e',
  wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6',
};
const statusColors = {
  pending: '#f59e0b', approved: '#38bdf8', executing: '#38bdf8',
  active: '#22c55e', assigned: '#f59e0b', review: '#a855f7',
  inbox: '#64748b', done: '#22c55e', dropped: '#64748b',
};
const typeIcons = { mission: LayoutGrid, action: ShieldCheck, workflow: Workflow };

export default function Delegations() {
  const [data, setData] = useState(null);
  const navigate = useNavigate();

  useEffect(() => { get('/delegations').then(d => d && setData(d)); }, []);

  if (!data) return <div className="flex items-center justify-center h-full"><span className="text-[var(--text-muted)] mono-heading pulse-active">loading...</span></div>;

  function handleClick(item) {
    if (item.type === 'mission') navigate('/missions');
    else if (item.type === 'action') navigate('/actions');
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="mono-heading text-2xl text-[var(--text-primary)]">delegations</h1>
          <span className="text-xs text-[var(--text-muted)]">
            {data.active?.length || 0} active · {data.completed?.length || 0} completed
          </span>
        </div>

        {/* Active */}
        {data.active?.length > 0 && (
          <div className="space-y-2">
            {data.active.map((item, i) => {
              const Icon = typeIcons[item.type] || LayoutGrid;
              const color = statusColors[item.status] || '#64748b';
              return (
                <div key={`${item.type}-${item.id}`} className="glass-card p-4 cursor-pointer hover:border-[var(--border-bright)] transition-colors" onClick={() => handleClick(item)}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <Icon size={14} style={{ color }} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-[10px] px-1.5 py-0.5 rounded mono-heading uppercase" style={{ color, backgroundColor: `${color}15` }}>{item.type}</span>
                          <span className="text-[10px] px-1.5 py-0.5 rounded mono-heading" style={{ color, backgroundColor: `${color}15` }}>{item.status}</span>
                          {item.agent && (
                            <span className="text-[10px] mono-heading" style={{ color: agentColors[item.agent] }}>@{item.agent}</span>
                          )}
                          {item.priority && (
                            <span className="text-[10px] text-[var(--text-muted)]">{item.priority}</span>
                          )}
                        </div>
                        <p className="text-sm text-[var(--text-primary)] truncate">{item.title}</p>
                      </div>
                    </div>
                    <span className="text-[10px] text-[var(--text-muted)] flex-shrink-0 ml-3">
                      {item.created_at ? new Date(item.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' }) : ''}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {data.active?.length === 0 && (
          <div className="text-center py-12">
            <CheckCircle size={32} className="mx-auto mb-3 text-[#22c55e]" />
            <p className="text-sm text-[var(--text-muted)]">all clear — nothing delegated</p>
          </div>
        )}

        {/* Completed */}
        {data.completed?.length > 0 && (
          <div>
            <span className="mono-heading text-xs text-[var(--text-muted)] mb-2 block">recently completed</span>
            <div className="space-y-1">
              {data.completed.map((item, i) => (
                <div key={`done-${item.id}`} className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] opacity-60">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <CheckCircle size={12} className="text-[#22c55e] flex-shrink-0" />
                    <p className="text-xs text-[var(--text-secondary)] truncate">{item.title}</p>
                    {item.agent && <span className="text-[10px]" style={{ color: agentColors[item.agent] }}>@{item.agent}</span>}
                  </div>
                  {item.result && <span className="text-[10px] text-[var(--text-muted)] max-w-[200px] truncate ml-2">{item.result}</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
