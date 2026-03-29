import { useState, useEffect } from 'react';
import { get } from '../api';

export default function Conversations() {
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    get('/conversations?limit=200').then(data => {
      if (data) setMessages(data);
    });
  }, []);

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold mb-4">Conversation History</h2>
      <div className="space-y-2">
        {messages.map((m, i) => (
          <div key={i} className={`p-3 rounded-lg text-sm ${
            m.role === 'user' ? 'bg-slate-800 border-l-2 border-amber-500' : 'bg-slate-900 border-l-2 border-slate-600'
          }`}>
            <div className="flex justify-between mb-1">
              <span className={`text-xs font-medium ${m.role === 'user' ? 'text-amber-400' : 'text-slate-500'}`}>
                {m.role === 'user' ? 'Maher' : 'Shams'}
              </span>
              <span className="text-xs text-slate-600">
                {m.timestamp ? new Date(m.timestamp).toLocaleString() : ''}
              </span>
            </div>
            <p className="text-slate-300 whitespace-pre-wrap">{m.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
