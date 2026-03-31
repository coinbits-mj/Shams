import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { Mail, Archive, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';

const priorityConfig = {
  P1: { color: '#ef4444', label: 'ACT NOW', bg: '#ef444415' },
  P2: { color: '#f59e0b', label: 'TODAY', bg: '#f59e0b15' },
  P3: { color: '#38bdf8', label: 'THIS WEEK', bg: '#38bdf815' },
  P4: { color: '#64748b', label: 'ARCHIVE', bg: '#64748b15' },
};

const agentColors = {
  shams: '#f59e0b', rumi: '#06b6d4', leo: '#22c55e',
  wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6',
};

export default function Inbox() {
  const [emails, setEmails] = useState([]);
  const [filter, setFilter] = useState('');
  const [accountFilter, setAccountFilter] = useState('');
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [expanded, setExpanded] = useState(null);

  async function load() {
    const params = new URLSearchParams({ archived: 'false' });
    if (filter) params.set('priority', filter);
    if (accountFilter) params.set('account', accountFilter);
    const data = await get(`/inbox?${params}`);
    if (data) setEmails(data);
  }

  useEffect(() => { load(); }, [filter, accountFilter]);

  async function runScan() {
    setScanning(true);
    setScanResult(null);
    const result = await post('/inbox/scan', { max_per_account: 50 });
    setScanResult(result);
    setScanning(false);
    load();
  }

  async function archiveOne(id) {
    await post(`/inbox/${id}/archive`);
    load();
  }

  async function batchArchiveP4() {
    const p4Ids = emails.filter(e => e.priority === 'P4' && !e.archived).map(e => e.id);
    if (p4Ids.length === 0) return;
    await post('/inbox/batch-archive', { ids: p4Ids });
    load();
  }

  async function batchArchiveAll(priority) {
    const ids = emails.filter(e => e.priority === priority && !e.archived).map(e => e.id);
    if (ids.length === 0) return;
    await post('/inbox/batch-archive', { ids });
    load();
  }

  const counts = { P1: 0, P2: 0, P3: 0, P4: 0 };
  emails.forEach(e => { if (counts[e.priority] !== undefined) counts[e.priority]++; });

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-[var(--border)] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <h2 className="mono-heading text-lg text-[var(--text-primary)]">inbox</h2>
          <span className="text-xs text-[var(--text-muted)]">
            <span className="text-[#ef4444]">{counts.P1}</span> urgent
            {' \u00b7 '}
            <span className="text-[#f59e0b]">{counts.P2}</span> today
            {' \u00b7 '}
            <span className="text-[#38bdf8]">{counts.P3}</span> week
            {' \u00b7 '}
            <span className="text-[#64748b]">{counts.P4}</span> archive
          </span>
        </div>
        <div className="flex items-center gap-3">
          {counts.P4 > 0 && (
            <button onClick={batchArchiveP4}
              className="text-xs px-3 py-1.5 rounded-lg bg-[#64748b20] text-[#64748b] border border-[#64748b30] hover:bg-[#64748b30] transition-colors mono-heading">
              <Archive size={12} className="inline mr-1" />archive all P4 ({counts.P4})
            </button>
          )}
          <button onClick={runScan} disabled={scanning}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors mono-heading flex items-center gap-1.5 ${
              scanning
                ? 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] cursor-wait'
                : 'bg-[var(--accent-glow)] text-[var(--accent)] border-[var(--border-bright)] hover:bg-[var(--accent)] hover:text-[var(--bg-deep)]'
            }`}>
            <RefreshCw size={12} className={scanning ? 'animate-spin' : ''} />
            {scanning ? 'scanning...' : 'scan inbox'}
          </button>
        </div>
      </div>

      {scanResult && (
        <div className="px-6 py-2 bg-[var(--accent-glow)] border-b border-[var(--border)]">
          <p className="text-xs text-[var(--accent)]">
            Scanned {scanResult.total_unread} unread emails, triaged {scanResult.triaged}.
          </p>
        </div>
      )}

      {/* Filters */}
      <div className="border-b border-[var(--border)] px-6 py-3 flex items-center gap-4">
        <div className="flex rounded-lg border border-[var(--border)] overflow-hidden">
          {['', 'P1', 'P2', 'P3', 'P4'].map(p => {
            const cfg = priorityConfig[p];
            return (
              <button key={p} onClick={() => setFilter(p)}
                className={`px-3 py-1.5 text-xs mono-heading transition-colors border-r border-[var(--border)] last:border-r-0 ${
                  filter === p ? 'bg-[var(--accent-glow)]' : 'hover:bg-[var(--bg-hover)]'
                }`}
                style={filter === p && cfg ? { color: cfg.color } : { color: 'var(--text-muted)' }}>
                {p || 'all'}
                {p && ` (${counts[p] || 0})`}
              </button>
            );
          })}
        </div>
        <div className="flex rounded-lg border border-[var(--border)] overflow-hidden">
          {['', 'personal', 'coinbits', 'qcc'].map(a => (
            <button key={a} onClick={() => setAccountFilter(a)}
              className={`px-3 py-1.5 text-xs mono-heading transition-colors border-r border-[var(--border)] last:border-r-0 ${
                accountFilter === a ? 'bg-[var(--accent-glow)] text-[var(--accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
              }`}>
              {a || 'all accounts'}
            </button>
          ))}
        </div>
      </div>

      {/* Email list */}
      <div className="flex-1 overflow-y-auto p-6">
        {emails.length === 0 && (
          <div className="text-center py-16">
            <Mail size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
            <p className="text-[var(--text-muted)] text-sm">
              {filter ? `No ${filter} emails` : 'No triaged emails. Click "scan inbox" to start.'}
            </p>
          </div>
        )}

        <div className="space-y-2">
          {emails.map(email => {
            const cfg = priorityConfig[email.priority] || priorityConfig.P4;
            const isExpanded = expanded === email.id;

            return (
              <div key={email.id} className="glass-card p-4">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-medium uppercase tracking-wider mono-heading"
                        style={{ color: cfg.color, backgroundColor: cfg.bg }}>
                        {email.priority}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)]">
                        {email.account}
                      </span>
                      {email.routed_to?.map(agent => (
                        <span key={agent} className="text-[10px] mono-heading" style={{ color: agentColors[agent] || '#64748b' }}>
                          @{agent}
                        </span>
                      ))}
                    </div>
                    <p className="text-sm text-[var(--text-primary)] mb-0.5">{email.subject || '(no subject)'}</p>
                    <p className="text-xs text-[var(--text-muted)] mb-1">{email.from_addr}</p>

                    {!isExpanded && email.action && (
                      <p className="text-xs text-[var(--text-secondary)] line-clamp-1">{email.action}</p>
                    )}

                    {isExpanded && (
                      <div className="mt-2 space-y-2">
                        {email.snippet && (
                          <p className="text-xs text-[var(--text-muted)] italic">{email.snippet}</p>
                        )}
                        {email.action && (
                          <div>
                            <span className="text-[10px] text-[var(--text-muted)] mono-heading">action: </span>
                            <span className="text-xs text-[var(--text-secondary)]">{email.action}</span>
                          </div>
                        )}
                        {email.draft_reply && (
                          <div className="bg-[var(--bg-deep)] p-3 rounded-lg border border-[var(--border)]">
                            <span className="text-[10px] text-[var(--text-muted)] mono-heading block mb-1">draft reply</span>
                            <p className="text-xs text-[var(--text-primary)] whitespace-pre-wrap">{email.draft_reply}</p>
                          </div>
                        )}
                      </div>
                    )}

                    <div className="flex items-center gap-3 mt-2">
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {email.triaged_at ? new Date(email.triaged_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                      </span>
                      <button onClick={() => setExpanded(isExpanded ? null : email.id)}
                        className="text-[10px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] flex items-center gap-0.5">
                        {isExpanded ? <><ChevronUp size={10} /> less</> : <><ChevronDown size={10} /> more</>}
                      </button>
                    </div>
                  </div>

                  <button onClick={() => archiveOne(email.id)}
                    className="ml-3 text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors flex-shrink-0"
                    title="Archive">
                    <Archive size={14} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
