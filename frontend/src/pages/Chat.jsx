import { useState, useRef, useEffect } from 'react';
import { post, get } from '../api';
import { Send } from 'lucide-react';

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => { get('/conversations?limit=30').then(d => d && setMessages(d)); }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  async function handleSend(e) {
    e.preventDefault();
    if (!input.trim() || loading) return;
    const msg = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: msg }]);
    setLoading(true);
    const data = await post('/chat', { message: msg });
    if (data?.reply) setMessages(prev => [...prev, { role: 'assistant', content: data.reply }]);
    setLoading(false);
  }

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-[var(--border)] px-6 py-4">
        <h2 className="mono-heading text-lg">chat with shams</h2>
      </div>
      <div className="flex-1 overflow-auto px-6 py-4 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[75%] rounded-xl px-4 py-3 text-sm whitespace-pre-wrap ${
              m.role === 'user'
                ? 'bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)]'
                : 'glass-card text-[var(--text-primary)]'
            }`}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="glass-card rounded-xl px-4 py-3 text-sm text-[var(--text-muted)]">
              <span className="pulse-active inline-block">thinking...</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={handleSend} className="border-t border-[var(--border)] px-6 py-4 flex gap-3">
        <input type="text" value={input} onChange={e => setInput(e.target.value)}
          placeholder="message shams..."
          className="flex-1 px-4 py-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] mono-heading text-sm" />
        <button type="submit" disabled={loading}
          className="px-4 py-3 bg-[var(--accent)] hover:bg-[#60ccf8] text-[var(--bg-deep)] rounded-xl transition-colors disabled:opacity-50">
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
