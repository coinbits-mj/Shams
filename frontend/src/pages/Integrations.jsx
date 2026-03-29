import { useState, useEffect } from 'react';
import { get } from '../api';
import { CheckCircle, XCircle, AlertCircle, Loader, ExternalLink } from 'lucide-react';

const statusIcon = {
  connected: <CheckCircle size={14} className="text-[var(--green)]" />,
  error: <XCircle size={14} className="text-[var(--red)]" />,
  unconfigured: <AlertCircle size={14} className="text-[var(--text-muted)]" />,
  checking: <Loader size={14} className="text-[var(--accent)] animate-spin" />,
};

const integrationDefs = [
  { id: 'telegram', category: 'messaging', name: 'Telegram', description: '@myshams_bot — primary chat interface', envKey: 'telegram' },
  { id: 'claude', category: 'ai', name: 'Claude (Anthropic)', description: 'Shams brain — conversation, analysis, tool use', envKey: 'claude' },
  { id: 'whisper', category: 'ai', name: 'OpenAI Whisper', description: 'Voice note transcription', envKey: 'whisper' },
  { id: 'mercury_clifton', category: 'banking', name: 'Mercury — Clifton', description: 'QCC Clifton café banking (51% owned)', envKey: 'mercury_clifton' },
  { id: 'mercury_plainfield', category: 'banking', name: 'Mercury — Plainfield + Production', description: 'QCC Plainfield café + wholesale (100% owned)', envKey: 'mercury_plainfield' },
  { id: 'mercury_personal', category: 'banking', name: 'Mercury — Personal', description: "Maher's personal banking (100%)", envKey: 'mercury_personal' },
  { id: 'mercury_coinbits', category: 'banking', name: 'Mercury — Coinbits', description: 'Coinbits company banking (40% owned)', envKey: 'mercury_coinbits' },
  { id: 'rumi', category: 'operations', name: 'Rumi (QCC Ops)', description: 'P&L, inventory, labor, scorecard, forecasting', envKey: 'rumi' },
  { id: 'resend', category: 'messaging', name: 'Resend', description: 'Magic link emails from shams@myshams.ai', envKey: 'resend' },
  { id: 'google_calendar', category: 'productivity', name: 'Google Calendar', description: "MJ's calendar — events, scheduling", envKey: 'google_calendar', oauth: 'google' },
  { id: 'gmail', category: 'productivity', name: 'Gmail', description: 'Inbox monitoring, email triage', envKey: 'gmail', oauth: 'google' },
  { id: 'square', category: 'operations', name: 'Square (via Rumi)', description: 'POS sales, items, labor timecards, catalog', envKey: 'square' },
  { id: 'marginedge', category: 'operations', name: 'MarginEdge (via Rumi)', description: 'Food costing, recipe COGS', envKey: 'marginedge' },
  { id: 'slack', category: 'messaging', name: 'Slack (via Rumi)', description: 'QCC team comms, waste logging, shift tasks', envKey: 'slack' },
  { id: 'leo', category: 'ai', name: 'Leo (Health Coach)', description: 'Biometrics, nutrition, sleep, recovery', envKey: 'leo' },
];

const categories = [
  { key: 'ai', label: 'ai & intelligence' },
  { key: 'banking', label: 'banking & finance' },
  { key: 'operations', label: 'operations' },
  { key: 'messaging', label: 'messaging & email' },
  { key: 'productivity', label: 'productivity' },
];

export default function Integrations() {
  const [statuses, setStatuses] = useState({});

  useEffect(() => {
    get('/integrations/status').then(d => {
      if (d) setStatuses(d);
    });
  }, []);

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="mono-heading text-lg">integrations</h2>
        <div className="flex gap-4 text-xs">
          <span className="text-[var(--text-muted)]">
            <span className="text-[var(--green)]">{Object.values(statuses).filter(s => s === 'connected').length}</span> connected
          </span>
          <span className="text-[var(--text-muted)]">
            <span className="text-[var(--text-secondary)]">{Object.values(statuses).filter(s => s === 'unconfigured').length}</span> unconfigured
          </span>
        </div>
      </div>

      {categories.map(cat => {
        const items = integrationDefs.filter(i => i.category === cat.key);
        if (items.length === 0) return null;
        return (
          <div key={cat.key} className="mb-6">
            <h3 className="mono-heading text-xs text-[var(--text-muted)] uppercase tracking-wider mb-3">{cat.label}</h3>
            <div className="space-y-2">
              {items.map(int => {
                const status = statuses[int.id] || 'checking';
                return (
                  <div key={int.id} className="glass-card p-4 flex items-center gap-4">
                    <div className="w-5">{statusIcon[status]}</div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-[var(--text-primary)]">{int.name}</span>
                        <span className={`mono-heading text-[10px] px-1.5 py-0.5 rounded ${
                          status === 'connected' ? 'bg-[rgba(34,197,94,0.1)] text-[var(--green)]' :
                          status === 'error' ? 'bg-[rgba(239,68,68,0.1)] text-[var(--red)]' :
                          'bg-[var(--bg-hover)] text-[var(--text-muted)]'
                        }`}>
                          {status}
                        </span>
                      </div>
                      <p className="text-xs text-[var(--text-muted)] mt-0.5">{int.description}</p>
                    </div>
                    {status === 'unconfigured' && int.oauth && (
                      <button
                        onClick={async () => {
                          const data = await get(`/integrations/${int.oauth}/connect`);
                          if (data?.url) window.location.href = data.url;
                        }}
                        className="flex items-center gap-1 px-3 py-1.5 bg-[var(--accent)] hover:bg-[#60ccf8] text-[var(--bg-deep)] rounded-lg text-xs mono-heading transition-colors"
                      >
                        connect <ExternalLink size={10} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
