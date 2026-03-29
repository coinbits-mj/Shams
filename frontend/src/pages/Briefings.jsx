import { useState, useEffect } from 'react';
import { get } from '../api';

export default function Briefings() {
  const [briefings, setBriefings] = useState([]);

  useEffect(() => {
    get('/briefings?limit=30').then(data => {
      if (data) setBriefings(data);
    });
  }, []);

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold mb-4">Briefing History</h2>
      <div className="space-y-4">
        {briefings.map((b, i) => (
          <div key={i} className="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <div className="flex items-center gap-3 mb-2">
              <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                b.type === 'morning' ? 'bg-amber-500/20 text-amber-400' : 'bg-blue-500/20 text-blue-400'
              }`}>
                {b.type}
              </span>
              <span className="text-xs text-slate-500">
                {b.delivered_at ? new Date(b.delivered_at).toLocaleString() : 'Not delivered'}
              </span>
              <span className="text-xs text-slate-600">via {b.channel}</span>
            </div>
            <p className="text-sm text-slate-300 whitespace-pre-wrap">{b.content}</p>
          </div>
        ))}
        {briefings.length === 0 && <p className="text-slate-500 text-sm">No briefings delivered yet.</p>}
      </div>
    </div>
  );
}
