import { useState, useRef, useEffect } from 'react';
import { post, get } from '../api';
import { Send } from 'lucide-react';

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    get('/conversations?limit=30').then(data => {
      if (data) setMessages(data);
    });
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleSend(e) {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const msg = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: msg }]);
    setLoading(true);

    const data = await post('/chat', { message: msg });
    if (data?.reply) {
      setMessages(prev => [...prev, { role: 'assistant', content: data.reply }]);
    }
    setLoading(false);
  }

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-slate-700 px-6 py-4">
        <h2 className="text-lg font-semibold">Chat with Shams</h2>
      </div>

      <div className="flex-1 overflow-auto px-6 py-4 space-y-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
              m.role === 'user'
                ? 'bg-amber-500/20 text-amber-100 border border-amber-500/30'
                : 'bg-slate-800 text-slate-200 border border-slate-700'
            }`}>
              {m.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-slate-800 border border-slate-700 rounded-2xl px-4 py-3 text-sm text-slate-400">
              Thinking...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSend} className="border-t border-slate-700 px-6 py-4 flex gap-3">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Message Shams..."
          className="flex-1 px-4 py-3 bg-slate-800 border border-slate-600 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-amber-400"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-4 py-3 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded-xl transition-colors disabled:opacity-50"
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
