import { useState, useEffect } from 'react';
import { get } from '../api';

export default function Mercury() {
  const [balances, setBalances] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [days, setDays] = useState(7);
  const [account, setAccount] = useState('');

  useEffect(() => {
    const q = account ? `?account=${account}` : '';
    get(`/mercury/balances${q}`).then(d => d && setBalances(d));
    get(`/mercury/transactions?days=${days}${account ? `&account=${account}` : ''}`).then(d => d && setTransactions(d));
  }, [account, days]);

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="mono-heading text-lg">mercury banking</h2>
        <div className="flex gap-2">
          <select value={account} onChange={e => setAccount(e.target.value)}
            className="px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm mono-heading">
            <option value="">all accounts</option>
            <option value="clifton">clifton (51%)</option>
            <option value="plainfield">plainfield + production (100%)</option>
            <option value="personal">personal (100%)</option>
            <option value="coinbits">coinbits (40%)</option>
          </select>
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            className="px-3 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm mono-heading">
            <option value={3}>3 days</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
        </div>
      </div>

      {balances && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          {balances.accounts?.map((a, i) => (
            <div key={i} className="glass-card p-4">
              <p className="mono-heading text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{a.entity}</p>
              <p className="text-[10px] text-[var(--text-muted)]">{a.account_name}</p>
              <p className={`text-xl font-semibold mt-2 mono-heading ${a.balance >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'}`}>
                ${a.balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </p>
              <p className="text-[10px] text-[var(--text-muted)] mt-1">{Math.round(a.ownership * 100)}% owned</p>
            </div>
          ))}
          <div className="glass-card p-4 glow-accent">
            <p className="mono-heading text-[10px] text-[var(--accent)] uppercase tracking-wider">grand total</p>
            <p className="text-xl font-semibold mt-2 mono-heading text-[var(--text-primary)]">
              ${balances.grand_total?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>
      )}

      <h3 className="mono-heading text-xs text-[var(--text-muted)] uppercase tracking-wider mb-3">recent transactions</h3>
      <div className="glass-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-[var(--text-muted)]">
              <th className="mono-heading text-[10px] text-left px-4 py-2 uppercase tracking-wider">date</th>
              <th className="mono-heading text-[10px] text-left px-4 py-2 uppercase tracking-wider">entity</th>
              <th className="mono-heading text-[10px] text-left px-4 py-2 uppercase tracking-wider">counterparty</th>
              <th className="mono-heading text-[10px] text-right px-4 py-2 uppercase tracking-wider">amount</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((t, i) => (
              <tr key={i} className="border-b border-[var(--border)] hover:bg-[var(--bg-hover)] transition-colors">
                <td className="px-4 py-2.5 text-[var(--text-muted)] text-xs">{t.date}</td>
                <td className="px-4 py-2.5 text-[var(--text-muted)] text-xs">{t.entity}</td>
                <td className="px-4 py-2.5 text-[var(--text-primary)]">{t.counterparty}</td>
                <td className={`px-4 py-2.5 text-right mono-heading ${t.amount >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'}`}>
                  {t.amount >= 0 ? '+' : ''}${t.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {transactions.length === 0 && <p className="text-[var(--text-muted)] text-sm p-4 text-center">no transactions found.</p>}
      </div>
    </div>
  );
}
