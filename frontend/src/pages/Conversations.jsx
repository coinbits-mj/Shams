import { useState, useEffect } from 'react';
import { get } from '../api';

export default function Conversations() {
  const [messages, setMessages] = useState([]);
  useEffect(() => { get('/conversations?limit=200').then(d => d && setMessages(d)); }, []);

  return (
    <div className="p-6">
      <h2 className="mono-heading text-lg mb-4">conversation history</h2>
      <div className="space-y-1.5">
        {messages.map((m, i) => (
          <div key={i} className={`p-3 rounded-lg text-sm border-l-2 ${
            m.role === 'user' ? 'bg-[var(--bg-card)] border-[var(--accent)]' : 'bg-[var(--bg-surface)] border-[var(--text-muted)]'
          }`}>
            <div className="flex justify-between mb-1">
              <span className={`mono-heading text-xs ${m.role === 'user' ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'}`}>
                {m.role === 'user' ? 'maher' : 'shams'}
              </span>
              <span className="text-[10px] text-[var(--text-muted)]">
                {m.timestamp ? new Date(m.timestamp).toLocaleString() : ''}
              </span>
            </div>
            <p className="text-[var(--text-secondary)] whitespace-pre-wrap">{m.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
