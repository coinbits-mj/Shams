import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { useNavigate } from 'react-router-dom';
import {
  DollarSign, TrendingUp, TrendingDown, Mail, ShieldCheck, LayoutGrid,
  Heart, Activity, Zap, Clock, ChevronRight, CheckCircle, AlertTriangle,
  Workflow, FileText
} from 'lucide-react';

const priorityColors = { urgent: '#ef4444', high: '#f97316', normal: '#38bdf8', low: '#64748b' };
const agentColors = {
  shams: '#f59e0b', rumi: '#06b6d4', leo: '#22c55e',
  wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6',
};

export default function Today() {
  const [data, setData] = useState(null);
  const [recentFiles, setRecentFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  async function load() {
    const [d, rf] = await Promise.all([get('/today'), get('/files/recent?limit=5')]);
    if (d) setData(d);
    if (rf) setRecentFiles(rf);
    setLoading(false);
  }

  useEffect(() => { load(); const i = setInterval(load, 30000); return () => clearInterval(i); }, []);

  async function approveAction(id) {
    await post(`/actions/${id}/approve`);
    load();
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-[var(--text-muted)] mono-heading pulse-active">loading today...</span>
      </div>
    );
  }

  if (!data) return null;

  const cash = data.cash || {};
  const pl = data.pl || {};
  const daily = pl.daily || {};
  const monthly = pl.monthly || {};
  const health = data.health || {};

  // Format currency
  const fmt = (n) => {
    if (n == null || n === undefined) return '—';
    return '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
  };

  const pct = (n) => {
    if (n == null) return '—';
    return Number(n).toFixed(1) + '%';
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="mono-heading text-2xl text-[var(--text-primary)]">today</h1>
            <p className="text-xs text-[var(--text-muted)] mt-1">
              {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
            </p>
          </div>
          {data.counts?.actions_pending > 0 && (
            <button onClick={() => navigate('/actions')}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#f59e0b20] text-[#f59e0b] border border-[#f59e0b30] mono-heading text-sm hover:bg-[#f59e0b30] transition-colors">
              <ShieldCheck size={14} />
              {data.counts.actions_pending} action{data.counts.actions_pending !== 1 ? 's' : ''} pending
            </button>
          )}
        </div>

        {/* Row 1: Money */}
        <div className="grid grid-cols-4 gap-3">
          <MetricCard
            label="cash position"
            value={fmt(cash.grand_total)}
            icon={DollarSign}
            color="#22c55e"
          />
          <MetricCard
            label="yesterday revenue"
            value={fmt(daily.revenue)}
            sub={daily.net_margin_pct != null ? `${pct(daily.net_margin_pct)} margin` : ''}
            icon={daily.net_margin_pct >= 0 ? TrendingUp : TrendingDown}
            color={daily.net_margin_pct >= 10 ? '#22c55e' : daily.net_margin_pct >= 0 ? '#f59e0b' : '#ef4444'}
          />
          <MetricCard
            label="MTD revenue"
            value={fmt(monthly.revenue)}
            sub={monthly.net_margin_pct != null ? `${pct(monthly.net_margin_pct)} margin` : ''}
            icon={TrendingUp}
            color="#38bdf8"
          />
          <MetricCard
            label="food cost"
            value={pct(daily.food_cost_pct)}
            sub={daily.labor_cost_pct != null ? `labor: ${pct(daily.labor_cost_pct)}` : ''}
            icon={Activity}
            color={daily.food_cost_pct <= 30 ? '#22c55e' : daily.food_cost_pct <= 35 ? '#f59e0b' : '#ef4444'}
            onClick={() => navigate('/mercury')}
          />
        </div>

        {/* Row 2: Needs Your Attention */}
        <div className="grid grid-cols-2 gap-4">
          {/* Pending Actions */}
          <div className="glass-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="mono-heading text-sm text-[var(--text-primary)] flex items-center gap-2">
                <ShieldCheck size={14} className="text-[#f59e0b]" /> pending actions
              </span>
              {data.pending_actions?.length > 0 && (
                <button onClick={() => navigate('/actions')} className="text-[10px] text-[var(--text-muted)] hover:text-[var(--accent)]">
                  view all <ChevronRight size={10} className="inline" />
                </button>
              )}
            </div>
            {data.pending_actions?.length > 0 ? (
              <div className="space-y-2">
                {data.pending_actions.map(a => (
                  <div key={a.id} className="flex items-center justify-between p-2 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)]">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] mono-heading" style={{ color: agentColors[a.agent_name] }}>{a.agent_name}</span>
                        <span className="text-[10px] text-[var(--text-muted)]">{a.action_type}</span>
                      </div>
                      <p className="text-xs text-[var(--text-primary)] truncate">{a.title}</p>
                    </div>
                    <button onClick={() => approveAction(a.id)}
                      className="ml-2 text-[10px] px-2 py-1 rounded bg-[#22c55e20] text-[#22c55e] border border-[#22c55e30] hover:bg-[#22c55e30] mono-heading flex-shrink-0">
                      approve
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--text-muted)] text-center py-4">all clear</p>
            )}
          </div>

          {/* Urgent Emails */}
          <div className="glass-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="mono-heading text-sm text-[var(--text-primary)] flex items-center gap-2">
                <Mail size={14} className="text-[#ef4444]" /> urgent emails
              </span>
              <button onClick={() => navigate('/inbox')} className="text-[10px] text-[var(--text-muted)] hover:text-[var(--accent)]">
                view inbox <ChevronRight size={10} className="inline" />
              </button>
            </div>
            {data.urgent_emails?.length > 0 ? (
              <div className="space-y-2">
                {data.urgent_emails.map(e => (
                  <div key={e.id} className="p-2 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)]">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-[10px] px-1.5 py-0.5 rounded mono-heading"
                        style={{ color: e.priority === 'P1' ? '#ef4444' : '#f59e0b', backgroundColor: e.priority === 'P1' ? '#ef444415' : '#f59e0b15' }}>
                        {e.priority}
                      </span>
                      <span className="text-[10px] text-[var(--text-muted)]">{e.account}</span>
                      {e.routed_to?.map(agent => (
                        <span key={agent} className="text-[10px]" style={{ color: agentColors[agent] }}>@{agent}</span>
                      ))}
                    </div>
                    <p className="text-xs text-[var(--text-primary)] truncate">{e.subject}</p>
                    <p className="text-[10px] text-[var(--text-muted)] truncate">{e.from_addr}</p>
                    {e.action && <p className="text-[10px] text-[var(--text-secondary)] mt-1 truncate">{e.action}</p>}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--text-muted)] text-center py-4">no urgent emails</p>
            )}
          </div>
        </div>

        {/* Row 3: Missions + Workflows + Health */}
        <div className="grid grid-cols-3 gap-4">
          {/* Active Missions */}
          <div className="glass-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="mono-heading text-sm text-[var(--text-primary)] flex items-center gap-2">
                <LayoutGrid size={14} className="text-[var(--accent)]" /> missions
              </span>
              <button onClick={() => navigate('/missions')} className="text-[10px] text-[var(--text-muted)] hover:text-[var(--accent)]">
                board <ChevronRight size={10} className="inline" />
              </button>
            </div>
            {data.missions?.length > 0 ? (
              <div className="space-y-1.5">
                {data.missions.slice(0, 6).map(m => (
                  <div key={m.id} className="flex items-center justify-between p-1.5 rounded bg-[var(--bg-deep)]">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <span className="text-[10px] px-1 rounded" style={{ color: priorityColors[m.priority], backgroundColor: `${priorityColors[m.priority]}15` }}>{m.priority}</span>
                      <span className="text-xs text-[var(--text-primary)] truncate">{m.title}</span>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {m.assigned_agent && <span className="text-[10px]" style={{ color: agentColors[m.assigned_agent] }}>{m.assigned_agent}</span>}
                      <span className="text-[10px] px-1 rounded bg-[var(--bg-hover)] text-[var(--text-muted)]">{m.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--text-muted)] text-center py-4">no active missions</p>
            )}
          </div>

          {/* Active Workflows */}
          <div className="glass-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="mono-heading text-sm text-[var(--text-primary)] flex items-center gap-2">
                <Workflow size={14} className="text-[#a855f7]" /> workflows
              </span>
            </div>
            {data.workflows?.length > 0 ? (
              <div className="space-y-2">
                {data.workflows.map(w => (
                  <div key={w.id} className="p-2 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)]">
                    <p className="text-xs text-[var(--text-primary)]">{w.title}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-[var(--text-muted)]">step {w.current_step}</span>
                      <div className="flex-1 h-1 rounded-full bg-[var(--bg-hover)]">
                        <div className="h-full rounded-full bg-[#a855f7] transition-all" style={{ width: '50%' }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--text-muted)] text-center py-4">no active workflows</p>
            )}
          </div>

          {/* Health */}
          <div className="glass-card p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="mono-heading text-sm text-[var(--text-primary)] flex items-center gap-2">
                <Heart size={14} className="text-[#22c55e]" /> health
              </span>
            </div>
            {health.weight || health.sleep ? (
              <div className="grid grid-cols-2 gap-3">
                {health.weight && (
                  <div className="text-center">
                    <p className="text-lg text-[var(--text-primary)] mono-heading">{health.weight}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">lbs</p>
                  </div>
                )}
                {health.sleep && (
                  <div className="text-center">
                    <p className="text-lg text-[var(--text-primary)] mono-heading">{Number(health.sleep).toFixed(1)}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">hours sleep</p>
                  </div>
                )}
                {health.hrv && (
                  <div className="text-center">
                    <p className="text-lg text-[var(--text-primary)] mono-heading">{Math.round(health.hrv)}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">HRV</p>
                  </div>
                )}
                {health.streak && (
                  <div className="text-center">
                    <p className="text-lg text-[#22c55e] mono-heading">{health.streak}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">day streak</p>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-[var(--text-muted)] text-center py-4">no health data</p>
            )}
          </div>
        </div>

        {/* Recent Files */}
        {recentFiles.length > 0 && (
          <div className="glass-card p-4">
            <span className="mono-heading text-sm text-[var(--text-primary)] flex items-center gap-2 mb-3">
              <FileText size={14} className="text-[#22c55e]" /> recent files
            </span>
            <div className="flex gap-3 overflow-x-auto">
              {recentFiles.map(f => (
                <div key={f.id} className="flex-shrink-0 p-2 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)] min-w-[180px] max-w-[220px] cursor-pointer hover:border-[var(--border-bright)]"
                  onClick={() => navigate('/projects')}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <FileText size={10} className="text-[#22c55e]" />
                    <span className="text-[11px] text-[var(--text-primary)] truncate">{f.filename}</span>
                  </div>
                  {f.mission_title && <p className="text-[9px] text-[var(--text-muted)] truncate">{f.mission_title}</p>}
                  <p className="text-[9px] text-[var(--text-muted)]">
                    {f.uploaded_at ? new Date(f.uploaded_at).toLocaleDateString([], { month: 'short', day: 'numeric' }) : ''}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Row 4: Recent Activity */}
        {data.recent_activity?.length > 0 && (
          <div className="glass-card p-4">
            <span className="mono-heading text-sm text-[var(--text-primary)] flex items-center gap-2 mb-3">
              <Clock size={14} className="text-[var(--text-muted)]" /> recent
            </span>
            <div className="flex gap-3 overflow-x-auto">
              {data.recent_activity.map((a, i) => (
                <div key={i} className="flex-shrink-0 p-2 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)] min-w-[200px] max-w-[250px]">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-[10px] mono-heading" style={{ color: agentColors[a.agent_name] || '#64748b' }}>{a.agent_name}</span>
                    <span className="text-[10px] text-[var(--text-muted)]">
                      {a.timestamp ? new Date(a.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                    </span>
                  </div>
                  <p className="text-[11px] text-[var(--text-secondary)] line-clamp-2">{a.content}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, icon: Icon, color, onClick }) {
  return (
    <div className={`glass-card p-4 ${onClick ? 'cursor-pointer hover:border-[var(--border-bright)]' : ''}`} onClick={onClick}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-[var(--text-muted)] mono-heading uppercase tracking-wider">{label}</span>
        <Icon size={14} style={{ color }} />
      </div>
      <p className="text-xl mono-heading" style={{ color }}>{value}</p>
      {sub && <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{sub}</p>}
    </div>
  );
}
