import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { Shield, ShieldCheck, ShieldX } from 'lucide-react';

const agentColors = {
  shams: '#f59e0b', rumi: '#06b6d4', leo: '#22c55e',
  wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6',
};

export default function Settings() {
  const [trust, setTrust] = useState([]);
  const [integrations, setIntegrations] = useState({});

  async function load() {
    const [t, i] = await Promise.all([get('/trust'), get('/integrations/status')]);
    if (t) setTrust(t);
    if (i) setIntegrations(i);
  }

  useEffect(() => { load(); }, []);

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
