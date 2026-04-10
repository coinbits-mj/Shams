import { useState, useEffect } from 'react';
import { get, post } from '../api';
import { Mail, Archive, RefreshCw, ChevronDown, ChevronUp, Zap, Star, Clock, FileEdit, X, ArrowRight, CheckCircle } from 'lucide-react';

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
  const [zeroMode, setZeroMode] = useState(false);
  const [currentEmail, setCurrentEmail] = useState(null);
  const [zeroProcessed, setZeroProcessed] = useState(0);
  const [zeroDone, setZeroDone] = useState(false);

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

  // ─── Inbox Zero Mode ────────────────────────────────────────────────
  async function startZero() {
    setZeroMode(true);
    setZeroProcessed(0);
    setZeroDone(false);
    await loadNextZero();
  }

  async function loadNextZero() {
    const data = await get('/inbox/zero/next');
    if (data?.done) {
      setZeroDone(true);
      setCurrentEmail(null);
    } else {
      setCurrentEmail(data?.email);
    }
  }

  async function zeroAction(action) {
    if (!currentEmail) return;
    if (action === 'archive') {
      await post(`/inbox/${currentEmail.id}/archive`);
    } else if (action === 'star') {
      await post(`/inbox/${currentEmail.id}/star`);
      // Star then archive — out of inbox but saved
      await post(`/inbox/${currentEmail.id}/archive`);
    } else if (action === 'draft') {
      await post(`/inbox/${currentEmail.id}/draft`, {});
      await post(`/inbox/${currentEmail.id}/archive`);
    } else if (action === 'skip') {
      // Just move on without doing anything
    }
    setZeroProcessed(p => p + 1);
    await loadNextZero();
  }

  function exitZero() {
    setZeroMode(false);
    setCurrentEmail(null);
    setZeroDone(false);
    load();
  }

  // Render Inbox Zero focused mode
  if (zeroMode) {
    return (
      <div className="flex flex-col h-full">
        <div className="border-b border-[var(--border)] px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap size={16} className="text-[var(--accent)]" />
            <h2 className="mono-heading text-lg text-[var(--text-primary)]">inbox zero</h2>
            <span className="text-xs text-[var(--text-muted)]">{zeroProcessed} processed</span>
          </div>
          <button onClick={exitZero} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 flex items-center justify-center p-8">
          {zeroDone ? (
            <div className="text-center">
              <CheckCircle size={48} className="mx-auto text-[#22c55e] mb-4" />
              <h3 className="text-2xl text-[var(--text-primary)] mono-heading mb-2">inbox zero</h3>
              <p className="text-sm text-[var(--text-muted)] mb-6">processed {zeroProcessed} emails</p>
              <button onClick={exitZero}
                className="px-4 py-2 rounded-lg bg-[var(--accent)] text-[var(--bg-deep)] mono-heading text-sm">
                done
              </button>
            </div>
          ) : currentEmail ? (
            <div className="max-w-2xl w-full">
              {/* Email card */}
              <div className="glass-card p-6 mb-6">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-[10px] px-1.5 py-0.5 rounded mono-heading"
                    style={{
                      color: priorityConfig[currentEmail.priority]?.color,
                      backgroundColor: priorityConfig[currentEmail.priority]?.bg
                    }}>
                    {currentEmail.priority}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)]">
                    {currentEmail.account}
                  </span>
                  {currentEmail.routed_to?.map(agent => (
                    <span key={agent} className="text-[10px] mono-heading" style={{ color: agentColors[agent] }}>@{agent}</span>
                  ))}
                </div>
                <h3 className="text-lg text-[var(--text-primary)] mb-1">{currentEmail.subject || '(no subject)'}</h3>
                <p className="text-xs text-[var(--text-muted)] mb-3">{currentEmail.from_addr}</p>
                {currentEmail.snippet && (
                  <p className="text-sm text-[var(--text-secondary)] italic mb-3">{currentEmail.snippet}</p>
                )}
                {currentEmail.action && (
                  <div className="mt-3 p-3 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)]">
                    <span className="text-[10px] text-[var(--text-muted)] mono-heading">recommended</span>
                    <p className="text-xs text-[var(--text-primary)] mt-1">{currentEmail.action}</p>
                  </div>
                )}
                {currentEmail.draft_reply && (
                  <div className="mt-2 p-3 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)]">
                    <span className="text-[10px] text-[var(--text-muted)] mono-heading">draft reply ready</span>
                    <p className="text-xs text-[var(--text-primary)] mt-1 whitespace-pre-wrap">{currentEmail.draft_reply.slice(0, 200)}{currentEmail.draft_reply.length > 200 ? '...' : ''}</p>
                  </div>
                )}
              </div>

              {/* Action buttons */}
              <div className="grid grid-cols-4 gap-3">
                <button onClick={() => zeroAction('archive')}
                  className="flex flex-col items-center gap-2 p-4 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] hover:border-[#64748b] transition-colors">
                  <Archive size={20} className="text-[#64748b]" />
                  <span className="text-xs mono-heading text-[var(--text-secondary)]">archive</span>
                </button>
                <button onClick={() => zeroAction('star')}
                  className="flex flex-col items-center gap-2 p-4 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] hover:border-[#f59e0b] transition-colors">
                  <Star size={20} className="text-[#f59e0b]" />
                  <span className="text-xs mono-heading text-[var(--text-secondary)]">star + archive</span>
                </button>
                <button onClick={() => zeroAction('draft')}
                  disabled={!currentEmail.draft_reply}
                  className="flex flex-col items-center gap-2 p-4 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] hover:border-[var(--accent)] transition-colors disabled:opacity-30">
                  <FileEdit size={20} className="text-[var(--accent)]" />
                  <span className="text-xs mono-heading text-[var(--text-secondary)]">draft reply</span>
                </button>
                <button onClick={() => zeroAction('skip')}
                  className="flex flex-col items-center gap-2 p-4 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] hover:border-[var(--border-bright)] transition-colors">
                  <ArrowRight size={20} className="text-[var(--text-muted)]" />
                  <span className="text-xs mono-heading text-[var(--text-secondary)]">skip</span>
                </button>
              </div>
              <p className="text-[10px] text-[var(--text-muted)] text-center mt-4">
                {zeroProcessed} processed in this session
              </p>
            </div>
          ) : (
            <p className="text-sm text-[var(--text-muted)] pulse-active">loading...</p>
          )}
        </div>
      </div>
    );
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
          {emails.length > 0 && (
            <button onClick={startZero}
              className="text-xs px-3 py-1.5 rounded-lg bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)] hover:bg-[var(--accent)] hover:text-[var(--bg-deep)] transition-colors mono-heading flex items-center gap-1.5">
              <Zap size={12} /> inbox zero
            </button>
          )}
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
