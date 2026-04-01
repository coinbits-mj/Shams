import { useState, useRef, useEffect } from 'react';
import { post, get, upload } from '../api';
import SmartMessage from '../components/SmartMessage';
import ChatInput from '../components/ChatInput';

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);
  const chatInputRef = useRef(null);

  useEffect(() => { get('/conversations?limit=30').then(d => d && setMessages(d)); }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  async function handleSend(message, files) {
    if ((!message && files.length === 0) || loading) return;

    const label = files.length > 0
      ? `${message || ''}${message ? ' ' : ''}[${files.map(f => f.name).join(', ')}]`
      : message;
    setMessages(prev => [...prev, { role: 'user', content: label }]);
    setLoading(true);

    let data;
    if (files.length > 0) {
      data = await upload('/chat', message, files);
    } else {
      data = await post('/chat', { message });
    }
    if (data?.reply) setMessages(prev => [...prev, { role: 'assistant', content: data.reply }]);
    setLoading(false);
  }

  return (
    <div className="flex flex-col h-full"
      onDragOver={e => e.preventDefault()}
      onDrop={e => { e.preventDefault(); chatInputRef.current?.addFiles(e.dataTransfer.files); }}
    >
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
              <SmartMessage content={m.content} />
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

      <ChatInput
        ref={chatInputRef}
        onSend={handleSend}
        placeholder="message shams... (/ for commands)"
        disabled={loading}
      />
    </div>
  );
}
