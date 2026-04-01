import { useState, useRef, useEffect } from 'react';
import { post, get, upload } from '../api';
import { Sun, Activity, Heart, Scale, Search, Wrench } from 'lucide-react';
import SmartMessage from '../components/SmartMessage';
import ChatInput from '../components/ChatInput';

const agentConfig = {
  maher: { color: '#e2e8f0', icon: null, label: 'Maher' },
  shams: { color: '#f59e0b', icon: Sun, label: 'Shams' },
  rumi: { color: '#06b6d4', icon: Activity, label: 'Rumi' },
  leo: { color: '#22c55e', icon: Heart, label: 'Leo' },
  wakil: { color: '#a855f7', icon: Scale, label: 'Wakil' },
  scout: { color: '#ef4444', icon: Search, label: 'Scout' },
  builder: { color: '#3b82f6', icon: Wrench, label: 'Builder' },
};

const WAR_ROOM_AGENTS = [
  { name: 'shams', color: '#f59e0b', icon: Sun, label: 'Shams' },
  { name: 'rumi', color: '#06b6d4', icon: Activity, label: 'Rumi' },
  { name: 'leo', color: '#22c55e', icon: Heart, label: 'Leo' },
  { name: 'wakil', color: '#a855f7', icon: Scale, label: 'Wakil' },
  { name: 'scout', color: '#ef4444', icon: Search, label: 'Scout' },
  { name: 'builder', color: '#3b82f6', icon: Wrench, label: 'Builder' },
];

export default function WarRoom() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);
  const chatInputRef = useRef(null);

  useEffect(() => {
    get('/group-chat/history?limit=50').then(d => d && setMessages(d));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleSend(message, files) {
    if ((!message && files.length === 0) || loading) return;

    const label = files.length > 0
      ? `${message || ''}${message ? ' ' : ''}[${files.map(f => f.name).join(', ')}]`
      : message;
    setMessages(prev => [...prev, { agent_name: 'maher', content: label, timestamp: new Date().toISOString() }]);
    setLoading(true);

    let data;
    if (files.length > 0) {
      data = await upload('/group-chat', message, files);
    } else {
      data = await post('/group-chat', { message });
    }
    if (data?.responses) {
      const newMsgs = data.responses.map(r => ({
        agent_name: r.agent,
        content: r.content,
        timestamp: new Date().toISOString(),
      }));
      setMessages(prev => [...prev, ...newMsgs]);
    }
    setLoading(false);
  }

  return (
    <div className="flex flex-col h-full"
      onDragOver={e => e.preventDefault()}
      onDrop={e => { e.preventDefault(); chatInputRef.current?.addFiles(e.dataTransfer.files); }}
    >
      {/* Header */}
      <div className="border-b border-[var(--border)] px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-[var(--green)] pulse-active" />
          <h2 className="mono-heading text-lg">war room</h2>
        </div>
        <div className="flex items-center gap-4">
          {['shams', 'rumi', 'leo', 'wakil', 'scout'].map(name => {
            const cfg = agentConfig[name];
            const Icon = cfg.icon;
            return (
              <div key={name} className="flex items-center gap-1.5">
                <Icon size={12} style={{ color: cfg.color }} />
                <span className="mono-heading text-xs" style={{ color: cfg.color }}>{cfg.label}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto px-6 py-4 space-y-3">
        {messages.map((m, i) => {
          const cfg = agentConfig[m.agent_name] || agentConfig.maher;
          const Icon = cfg.icon;
          const isUser = m.agent_name === 'maher';

          return (
            <div key={i} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] ${isUser ? '' : 'flex gap-3'}`}>
                {!isUser && (
                  <div className="flex-shrink-0 mt-1">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center"
                      style={{ backgroundColor: `${cfg.color}15`, border: `1px solid ${cfg.color}30` }}>
                      {Icon && <Icon size={14} style={{ color: cfg.color }} />}
                    </div>
                  </div>
                )}
                <div>
                  {!isUser && (
                    <span className="mono-heading text-[11px] ml-1 mb-1 block" style={{ color: cfg.color }}>
                      {cfg.label}
                    </span>
                  )}
                  <div className={`rounded-xl px-4 py-3 text-sm whitespace-pre-wrap ${
                    isUser
                      ? 'bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-primary)]'
                      : 'border'
                  }`}
                    style={!isUser ? {
                      backgroundColor: `${cfg.color}08`,
                      borderColor: `${cfg.color}20`,
                      color: 'var(--text-primary)',
                    } : {}}>
                    <SmartMessage content={m.content} />
                  </div>
                  <span className="text-[10px] text-[var(--text-muted)] ml-1 mt-0.5 block">
                    {m.timestamp ? new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                  </span>
                </div>
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex justify-start">
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--amber-glow)] border border-[rgba(245,158,11,0.3)]">
                <Sun size={14} className="text-[var(--amber)] pulse-active" />
              </div>
              <div>
                <span className="mono-heading text-[11px] text-[var(--text-muted)] ml-1 mb-1 block">agents thinking...</span>
                <div className="glass-card rounded-xl px-4 py-3 text-sm text-[var(--text-muted)]">
                  <span className="pulse-active inline-block">gathering intel from all agents...</span>
                </div>
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <ChatInput
        ref={chatInputRef}
        onSend={handleSend}
        placeholder="message the squad... (@ to mention, / for commands)"
        disabled={loading}
        agents={WAR_ROOM_AGENTS}
      />
    </div>
  );
}
