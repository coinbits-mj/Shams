import { useState, useEffect } from 'react';
import { get, post, patch } from '../api';
import { Shield, ShieldCheck, ShieldX, Zap, Bell, Clock } from 'lucide-react';

const agentColors = {
  shams: '#f59e0b', rumi: '#06b6d4', leo: '#22c55e',
  wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6',
};

export default function Settings() {
  const [trust, setTrust] = useState([]);
  const [integrations, setIntegrations] = useState({});
  const [scheduledTasks, setScheduledTasks] = useState([]);
  const [alertRules, setAlertRules] = useState([]);

  const TEMPLATES = [
    { name: 'Morning Briefing', cron: '0 11 * * 1-5', prompt: 'Give me a morning briefing: cash summary, yesterday P&L, P1/P2 emails, open missions, health check. Keep it tight.', icon: '☀️' },
    { name: 'Auto Inbox Triage', cron: '0 */2 * * *', prompt: 'Triage my inbox — scan all accounts for new emails.', icon: '📧' },
    { name: 'Weekly Deal Scan', cron: '0 14 * * 1', prompt: 'Search for specialty coffee businesses for sale in NJ, commercial real estate in Somerville NJ, and coffee industry M&A news. Add any promising finds to the deal pipeline.', icon: '🔍' },
    { name: 'Daily Cash Alert', cron: '0 15 * * 1-5', prompt: 'Check cash across all Mercury accounts. If total is below $40K, tell me immediately. Otherwise just give me the number.', icon: '💰' },
    { name: 'Weekly P&L Summary', cron: '0 22 * * 5', prompt: 'Give me a full week summary: total revenue, margins, food cost, labor cost, net profit. Compare to last week if possible.', icon: '📊' },
    { name: 'Evening Wrap-up', cron: '0 1 * * 2-6', prompt: 'Give me an evening wrap: what got done today, what\'s still open, any P1 items for tomorrow. Keep it short.', icon: '🌙' },
  ];

  async function load() {
    const [t, i, st, ar] = await Promise.all([
      get('/trust'), get('/integrations/status'), get('/scheduled-tasks'), get('/alert-rules'),
    ]);
    if (t) setTrust(t);
    if (i) setIntegrations(i);
    if (st) setScheduledTasks(st);
    if (ar) setAlertRules(ar);
  }

  useEffect(() => { load(); }, []);

  async function enableTemplate(template) {
    await post('/scheduled-tasks', { name: template.name, cron_expression: template.cron, prompt: template.prompt });
    load();
  }

  async function toggleTask(taskId, enabled) {
    await patch(`/scheduled-tasks/${taskId}`, { enabled: !enabled });
    load();
  }

  async function toggleAlertRule(ruleId, enabled) {
    await patch(`/alert-rules/${ruleId}`, { enabled: !enabled });
    load();
  }

  async function toggleAutoApprove(agent, current) {
    await post(`/trust/${agent}/auto-approve`, { enabled: !current });
    load();
  }

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-[var(--border)] px-6 py-4">
        <h2 className="mono-heading text-lg text-[var(--text-primary)]">settings</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-8">
        {/* Trust Scores */}
        <div>
          <h3 className="mono-heading text-sm text-[var(--text-primary)] mb-4 flex items-center gap-2">
            <Shield size={16} /> agent trust levels
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {trust.map(t => {
              const color = agentColors[t.agent_name] || '#64748b';
              return (
                <div key={t.agent_name} className="glass-card p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                      <span className="mono-heading text-sm" style={{ color }}>{t.agent_name}</span>
                    </div>
                    <button
                      onClick={() => toggleAutoApprove(t.agent_name, t.auto_approve)}
                      className={`text-[10px] px-2 py-1 rounded-lg border transition-colors mono-heading flex items-center gap-1 ${
                        t.auto_approve
                          ? 'bg-[#22c55e20] text-[#22c55e] border-[#22c55e30]'
                          : t.eligible_for_auto
                            ? 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:border-[#22c55e30] hover:text-[#22c55e]'
                            : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] opacity-50 cursor-not-allowed'
                      }`}
                      disabled={!t.eligible_for_auto && !t.auto_approve}
                      title={!t.eligible_for_auto && !t.auto_approve ? 'Needs 10+ actions with 90%+ approval' : ''}
                    >
                      {t.auto_approve ? <><ShieldCheck size={10} /> auto-approve on</> : <><ShieldX size={10} /> auto-approve off</>}
                    </button>
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <p className="text-lg text-[var(--text-primary)] mono-heading">{t.total_proposed}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">proposed</p>
                    </div>
                    <div>
                      <p className="text-lg text-[#22c55e] mono-heading">{t.total_approved}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">approved</p>
                    </div>
                    <div>
                      <p className="text-lg text-[#ef4444] mono-heading">{t.total_rejected}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">rejected</p>
                    </div>
                  </div>

                  {/* Approval rate bar */}
                  <div className="mt-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-[var(--text-muted)]">approval rate</span>
                      <span className="text-[10px] mono-heading" style={{
                        color: t.approval_rate >= 90 ? '#22c55e' : t.approval_rate >= 70 ? '#f59e0b' : '#ef4444'
                      }}>{t.approval_rate}%</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-[var(--bg-deep)]">
                      <div className="h-full rounded-full transition-all" style={{
                        width: `${t.approval_rate}%`,
                        backgroundColor: t.approval_rate >= 90 ? '#22c55e' : t.approval_rate >= 70 ? '#f59e0b' : '#ef4444',
                      }} />
                    </div>
                  </div>
                </div>
              );
            })}
            {trust.length === 0 && (
              <p className="text-xs text-[var(--text-muted)] col-span-3 text-center py-8">
                No trust data yet. Trust scores build as agents propose actions.
              </p>
            )}
          </div>
          <p className="text-[10px] text-[var(--text-muted)] mt-3">
            Auto-approve unlocks after 10+ actions with 90%+ approval rate. Any rejection resets eligibility.
          </p>
        </div>

        {/* Automation Templates */}
        <div>
          <h3 className="mono-heading text-sm text-[var(--text-primary)] mb-4 flex items-center gap-2">
            <Zap size={16} className="text-[var(--accent)]" /> automation templates
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {TEMPLATES.map(t => {
              const active = scheduledTasks.some(st => st.name === t.name && st.enabled);
              return (
                <div key={t.name} className="glass-card p-4 flex items-start justify-between">
                  <div>
                    <p className="text-sm text-[var(--text-primary)] mb-1">{t.icon} {t.name}</p>
                    <p className="text-[10px] text-[var(--text-muted)] mono-heading">{t.cron}</p>
                  </div>
                  <button onClick={() => active ? null : enableTemplate(t)}
                    className={`text-[10px] px-2 py-1 rounded-lg border mono-heading ${
                      active
                        ? 'bg-[#22c55e20] text-[#22c55e] border-[#22c55e30]'
                        : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--accent)] hover:text-[var(--accent)]'
                    }`}>
                    {active ? 'active' : 'enable'}
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {/* Active Scheduled Tasks */}
        {scheduledTasks.length > 0 && (
          <div>
            <h3 className="mono-heading text-sm text-[var(--text-primary)] mb-4 flex items-center gap-2">
              <Clock size={16} /> scheduled tasks
            </h3>
            <div className="space-y-2">
              {scheduledTasks.map(t => (
                <div key={t.id} className="glass-card p-3 flex items-center justify-between">
                  <div>
                    <p className="text-xs text-[var(--text-primary)]">{t.name}</p>
                    <p className="text-[10px] text-[var(--text-muted)] mono-heading">
                      {t.cron_expression} · last run: {t.last_run_at ? new Date(t.last_run_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'never'}
                    </p>
                  </div>
                  <button onClick={() => toggleTask(t.id, t.enabled)}
                    className={`text-[10px] px-2 py-1 rounded-lg border mono-heading ${
                      t.enabled ? 'bg-[#22c55e20] text-[#22c55e] border-[#22c55e30]' : 'text-[var(--text-muted)] border-[var(--border)]'
                    }`}>
                    {t.enabled ? 'on' : 'off'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Alert Rules */}
        <div>
          <h3 className="mono-heading text-sm text-[var(--text-primary)] mb-4 flex items-center gap-2">
            <Bell size={16} className="text-[#f59e0b]" /> smart alerts
          </h3>
          {alertRules.length > 0 ? (
            <div className="space-y-2">
              {alertRules.map(r => (
                <div key={r.id} className="glass-card p-3 flex items-center justify-between">
                  <div>
                    <p className="text-xs text-[var(--text-primary)]">{r.name}</p>
                    <p className="text-[10px] text-[var(--text-muted)] mono-heading">
                      {r.metric} {r.condition} {r.threshold} · {r.last_triggered ? `last: ${new Date(r.last_triggered).toLocaleDateString()}` : 'never triggered'}
                    </p>
                  </div>
                  <button onClick={() => toggleAlertRule(r.id, r.enabled)}
                    className={`text-[10px] px-2 py-1 rounded-lg border mono-heading ${
                      r.enabled ? 'bg-[#f59e0b20] text-[#f59e0b] border-[#f59e0b30]' : 'text-[var(--text-muted)] border-[var(--border)]'
                    }`}>
                    {r.enabled ? 'on' : 'off'}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-[var(--text-muted)]">No alert rules configured. Tell Shams "alert me if cash drops below $30K" to create one.</p>
          )}
        </div>

        {/* Connected Accounts */}
        <div>
          <h3 className="mono-heading text-sm text-[var(--text-primary)] mb-4">connected services</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
            {Object.entries(integrations).map(([key, status]) => (
              <div key={key} className="glass-card p-3 flex items-center justify-between">
                <span className="text-xs text-[var(--text-secondary)] mono-heading">{key.replace(/_/g, ' ')}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                  status === 'connected' ? 'text-[#22c55e] bg-[#22c55e15]' :
                  status === 'error' ? 'text-[#ef4444] bg-[#ef444415]' :
                  'text-[var(--text-muted)] bg-[var(--bg-hover)]'
                }`}>{status}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
