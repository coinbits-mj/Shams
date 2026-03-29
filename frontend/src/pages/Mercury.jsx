import { useState, useEffect } from 'react';
import { get } from '../api';

export default function Mercury() {
  const [balances, setBalances] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [days, setDays] = useState(7);
  const [account, setAccount] = useState('');

  async function loadBalances() {
    const data = await get(`/mercury/balances${account ? `?account=${account}` : ''}`);
    if (data) setBalances(data);
  }

  async function loadTransactions() {
    const data = await get(`/mercury/transactions?days=${days}${account ? `&account=${account}` : ''}`);
    if (data) setTransactions(data);
  }

  useEffect(() => { loadBalances(); loadTransactions(); }, [account, days]);

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-semibold">Mercury Banking</h2>
        <div className="flex gap-2">
          <select value={account} onChange={e => setAccount(e.target.value)}
            className="px-3 py-1.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm">
            <option value="">All Accounts</option>
            <option value="clifton">Clifton (51%)</option>
            <option value="plainfield">Plainfield + Production (100%)</option>
            <option value="personal">Personal (100%)</option>
            <option value="coinbits">Coinbits (40%)</option>
          </select>
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            className="px-3 py-1.5 bg-slate-800 border border-slate-600 rounded-lg text-white text-sm">
            <option value={3}>3 days</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
        </div>
      </div>

      {/* Balances */}
      {balances && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {balances.accounts?.map((a, i) => (
            <div key={i} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
              <p className="text-xs text-slate-500">{a.entity}</p>
              <p className="text-xs text-slate-400">{a.account_name}</p>
              <p className={`text-xl font-semibold mt-1 ${a.balance >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ${a.balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </p>
              <p className="text-xs text-slate-600 mt-1">{Math.round(a.ownership * 100)}% owned</p>
            </div>
          ))}
          <div className="bg-slate-800 border border-amber-500/30 rounded-xl p-4">
            <p className="text-xs text-amber-400">Grand Total</p>
            <p className="text-xl font-semibold mt-1 text-white">
              ${balances.grand_total?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>
      )}

      {/* Transactions */}
      <h3 className="text-sm font-medium text-slate-400 mb-3">Recent Transactions</h3>
      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 text-slate-500 text-xs">
              <th className="text-left px-4 py-2">Date</th>
              <th className="text-left px-4 py-2">Entity</th>
              <th className="text-left px-4 py-2">Counterparty</th>
              <th className="text-right px-4 py-2">Amount</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((t, i) => (
              <tr key={i} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                <td className="px-4 py-2 text-slate-400">{t.date}</td>
                <td className="px-4 py-2 text-slate-500 text-xs">{t.entity}</td>
                <td className="px-4 py-2 text-slate-200">{t.counterparty}</td>
                <td className={`px-4 py-2 text-right font-mono ${t.amount >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {t.amount >= 0 ? '+' : ''}${t.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {transactions.length === 0 && (
          <p className="text-slate-500 text-sm p-4 text-center">No transactions found.</p>
        )}
      </div>
    </div>
  );
}
