import { useState, useEffect } from 'react';
import { get } from '../api';
import { DollarSign, TrendingUp, TrendingDown, AlertTriangle, Activity, ArrowRight } from 'lucide-react';

export default function Money() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    get('/money').then(d => { if (d) setData(d); setLoading(false); });
  }, []);

  if (loading) return <div className="flex items-center justify-center h-full"><span className="text-[var(--text-muted)] mono-heading pulse-active">loading financials...</span></div>;
  if (!data) return null;

  const fmt = n => n == null ? '—' : '$' + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
  const pct = n => n == null ? '—' : Number(n).toFixed(1) + '%';
  const cash = data.cash || {};
  const daily = data.daily_pl || {};
  const monthly = data.monthly_pl || {};
  const forecast = data.forecast || {};
  const labor = data.labor || {};
  const scorecard = data.scorecard || {};
  const alerts = data.alerts || [];
  const accounts = cash.accounts || [];
  const transactions = data.transactions || [];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Header + Alerts */}
        <div className="flex items-center justify-between">
          <h1 className="mono-heading text-2xl text-[var(--text-primary)]">money</h1>
          {alerts.length > 0 && (
            <div className="flex gap-2">
              {alerts.map((a, i) => (
                <span key={i} className={`text-xs px-3 py-1.5 rounded-lg border mono-heading flex items-center gap-1.5 ${
                  a.level === 'critical' ? 'bg-[#ef444420] text-[#ef4444] border-[#ef444430]' : 'bg-[#f59e0b20] text-[#f59e0b] border-[#f59e0b30]'
                }`}>
                  <AlertTriangle size={12} /> {a.message}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Cash Position */}
        <div className="glass-card p-5">
          <div className="flex items-center justify-between mb-4">
            <span className="mono-heading text-sm text-[var(--text-muted)]">total cash position</span>
            <DollarSign size={16} className="text-[#22c55e]" />
          </div>
          <p className="text-3xl mono-heading text-[#22c55e] mb-4">{fmt(cash.grand_total)}</p>
          {accounts.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {accounts.map((acct, i) => (
                <div key={i} className="p-3 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)]">
                  <p className="text-[10px] text-[var(--text-muted)] mono-heading uppercase">{acct.name || acct.account || `Account ${i + 1}`}</p>
                  <p className="text-sm text-[var(--text-primary)] mono-heading mt-1">{fmt(acct.balance || acct.available_balance)}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* P&L Row */}
        <div className="grid grid-cols-2 gap-4">
          {/* Yesterday */}
          <div className="glass-card p-5">
            <span className="mono-heading text-sm text-[var(--text-muted)]">yesterday</span>
            <div className="grid grid-cols-3 gap-4 mt-3">
              <div>
                <p className="text-[10px] text-[var(--text-muted)] mono-heading">revenue</p>
                <p className="text-xl mono-heading text-[var(--text-primary)]">{fmt(daily.revenue)}</p>
              </div>
              <div>
                <p className="text-[10px] text-[var(--text-muted)] mono-heading">net margin</p>
                <p className="text-xl mono-heading" style={{ color: (daily.net_margin_pct || 0) >= 10 ? '#22c55e' : (daily.net_margin_pct || 0) >= 0 ? '#f59e0b' : '#ef4444' }}>
                  {pct(daily.net_margin_pct)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-[var(--text-muted)] mono-heading">net profit</p>
                <p className="text-xl mono-heading text-[var(--text-primary)]">{fmt(daily.net_profit)}</p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4 mt-4">
              <CostMetric label="food cost" value={daily.food_cost_pct} threshold={30} high={35} />
              <CostMetric label="labor cost" value={daily.labor_cost_pct} threshold={30} high={35} />
              <CostMetric label="overhead" value={daily.overhead_pct} threshold={15} high={20} />
            </div>
          </div>

          {/* Month to Date */}
          <div className="glass-card p-5">
            <span className="mono-heading text-sm text-[var(--text-muted)]">month to date</span>
            <div className="grid grid-cols-3 gap-4 mt-3">
              <div>
                <p className="text-[10px] text-[var(--text-muted)] mono-heading">revenue</p>
                <p className="text-xl mono-heading text-[var(--text-primary)]">{fmt(monthly.revenue)}</p>
              </div>
              <div>
                <p className="text-[10px] text-[var(--text-muted)] mono-heading">net margin</p>
                <p className="text-xl mono-heading" style={{ color: (monthly.net_margin_pct || 0) >= 10 ? '#22c55e' : '#f59e0b' }}>
                  {pct(monthly.net_margin_pct)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-[var(--text-muted)] mono-heading">net profit</p>
                <p className="text-xl mono-heading text-[var(--text-primary)]">{fmt(monthly.net_profit)}</p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4 mt-4">
              <CostMetric label="food cost" value={monthly.food_cost_pct} threshold={30} high={35} />
              <CostMetric label="labor cost" value={monthly.labor_cost_pct} threshold={30} high={35} />
              <CostMetric label="overhead" value={monthly.overhead_pct} threshold={15} high={20} />
            </div>
          </div>
        </div>

        {/* Recent Transactions */}
        {transactions.length > 0 && (
          <div className="glass-card p-5">
            <span className="mono-heading text-sm text-[var(--text-muted)] mb-3 block">recent transactions (7 days)</span>
            <div className="space-y-1">
              {transactions.slice(0, 15).map((t, i) => {
                const amount = t.amount || t.displayAmount || 0;
                const isNeg = amount < 0 || String(amount).startsWith('-');
                return (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-[var(--bg-deep)]">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-[var(--text-primary)] truncate">{t.description || t.counterpartyName || t.friendlyDescription || 'Transaction'}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">{t.date || t.postedAt || ''} {t.account ? `· ${t.account}` : ''}</p>
                    </div>
                    <span className={`text-sm mono-heading flex-shrink-0 ml-3 ${isNeg ? 'text-[var(--text-primary)]' : 'text-[#22c55e]'}`}>
                      {typeof amount === 'number' ? fmt(Math.abs(amount)) : amount}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function CostMetric({ label, value, threshold, high }) {
  const color = value == null ? 'var(--text-muted)' : value <= threshold ? '#22c55e' : value <= high ? '#f59e0b' : '#ef4444';
  return (
    <div>
      <p className="text-[10px] text-[var(--text-muted)] mono-heading">{label}</p>
      <div className="flex items-center gap-2 mt-1">
        <p className="text-sm mono-heading" style={{ color }}>{value != null ? value.toFixed(1) + '%' : '—'}</p>
        {value != null && (
          <div className="flex-1 h-1.5 rounded-full bg-[var(--bg-hover)]">
            <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(value, 50) * 2}%`, backgroundColor: color }} />
          </div>
        )}
      </div>
    </div>
  );
}
