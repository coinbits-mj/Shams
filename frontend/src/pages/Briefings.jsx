import { useState, useEffect } from 'react';
import { get } from '../api';

export default function Briefings() {
  const [briefings, setBriefings] = useState([]);
  useEffect(() => { get('/briefings?limit=30').then(d => d && setBriefings(d)); }, []);

  return (
    <div className="p-6">
      <h2 className="mono-heading text-lg mb-4">briefing history</h2>
      <div className="space-y-3">
        {briefings.map((b, i) => (
          <div key={i} className="glass-card p-4">
            <div className="flex items-center gap-3 mb-2">
              <span className={`mono-heading text-xs px-2 py-0.5 rounded ${
                b.type === 'morning' ? 'bg-[var(--amber-glow)] text-[var(--amber)]' : 'bg-[var(--accent-glow)] text-[var(--accent)]'
              }`}>
                {b.type}
              </span>
              <span className="text-[10px] text-[var(--text-muted)]">
                {b.delivered_at ? new Date(b.delivered_at).toLocaleString() : 'pending'}
              </span>
            </div>
            <p className="text-sm text-[var(--text-secondary)] whitespace-pre-wrap">{b.content}</p>
          </div>
        ))}
        {briefings.length === 0 && <p className="text-[var(--text-muted)] text-sm">no briefings delivered yet.</p>}
      </div>
    </div>
  );
}
