import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react';
import { Send, Paperclip, X, FileText, Image } from 'lucide-react';

const SLASH_COMMANDS = [
  { command: 'inbox',     args: '',          description: 'Triage inbox',          transform: () => 'triage my inbox' },
  { command: 'cash',      args: '',          description: 'Cash summary',          transform: () => 'give me a cash summary across all accounts' },
  { command: 'pl',        args: '',          description: "Today's P&L",           transform: () => "what's today's P&L?" },
  { command: 'health',    args: '',          description: 'Health summary',        transform: () => 'give me my health summary' },
  { command: 'scorecard', args: '',          description: 'Location scorecard',    transform: () => 'show me the location health scorecard' },
  { command: 'forecast',  args: '',          description: 'Cash flow forecast',    transform: () => 'show me the cash flow forecast' },
  { command: 'search',    args: '[query]',   description: 'Web search',            transform: (a) => `search the web for: ${a}` },
  { command: 'email',     args: '[query]',   description: 'Search email',          transform: (a) => `search my email for: ${a}` },
  { command: 'research',  args: '[query]',   description: 'Assign Scout research', transform: (a) => `assign research to scout: ${a}` },
  { command: 'draft',     args: '[type]',    description: 'Draft legal document',  transform: (a) => `draft a ${a}` },
  { command: 'mission',   args: '[title]',   description: 'Create mission',        transform: (a) => `create a new mission: ${a}` },
  { command: 'labor',     args: '',          description: 'Labor analysis',        transform: () => 'show me the labor analysis' },
  { command: 'inventory', args: '',          description: 'Inventory alerts',      transform: () => 'any inventory alerts?' },
];

const ChatInput = forwardRef(function ChatInput({ onSend, placeholder, disabled, agents, fileAccept }, ref) {
  const [input, setInput] = useState('');
  const [files, setFiles] = useState([]);
  const [dropdown, setDropdown] = useState(null); // { type: 'mention'|'command', items: [], activeIndex: 0, triggerStart: number }
  const textareaRef = useRef(null);
  const fileRef = useRef(null);
  const dropdownRef = useRef(null);

  // Expose addFiles for parent drag-drop
  useImperativeHandle(ref, () => ({
    addFiles(fileList) {
      setFiles(prev => [...prev, ...Array.from(fileList)]);
    }
  }));

  // Auto-resize textarea
  useEffect(() => {
    autoResize();
  }, [input]);

  function autoResize() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  // Scroll active dropdown item into view
  useEffect(() => {
    if (!dropdown || !dropdownRef.current) return;
    const active = dropdownRef.current.querySelector('[data-active="true"]');
    if (active) active.scrollIntoView({ block: 'nearest' });
  }, [dropdown?.activeIndex]);

  function handleChange(e) {
    const value = e.target.value;
    setInput(value);
    detectDropdown(value, e.target.selectionStart);
  }

  function detectDropdown(text, cursorPos) {
    const beforeCursor = text.slice(0, cursorPos);

    // Check @mention — find @ not preceded by non-space (or at start)
    const mentionMatch = beforeCursor.match(/(?:^|\s)@(\w*)$/);
    if (mentionMatch && agents && agents.length > 0) {
      const query = mentionMatch[1].toLowerCase();
      const triggerStart = beforeCursor.lastIndexOf('@');
      let filtered = agents;
      if (query) {
        filtered = agents.filter(a =>
          a.name.startsWith(query) || a.label.toLowerCase().startsWith(query)
        );
      }
      // Add @group option
      const groupOption = { name: 'group', color: '#38bdf8', label: 'Everyone', isGroup: true };
      if (!query || 'group'.startsWith(query) || 'everyone'.startsWith(query) || 'team'.startsWith(query)) {
        filtered = [...filtered, groupOption];
      }
      if (filtered.length > 0) {
        setDropdown({ type: 'mention', items: filtered, activeIndex: 0, triggerStart });
        return;
      }
    }

    // Check /command — only at start of input
    const cmdMatch = beforeCursor.trimStart().match(/^\/(\w*)$/);
    if (cmdMatch) {
      const query = cmdMatch[1].toLowerCase();
      const triggerStart = beforeCursor.indexOf('/');
      let filtered = SLASH_COMMANDS;
      if (query) {
        filtered = SLASH_COMMANDS.filter(c =>
          c.command.startsWith(query) || c.description.toLowerCase().includes(query)
        );
      }
      if (filtered.length > 0) {
        setDropdown({ type: 'command', items: filtered, activeIndex: 0, triggerStart });
        return;
      }
    }

    setDropdown(null);
  }

  function selectMention(agent) {
    const before = input.slice(0, dropdown.triggerStart);
    const after = input.slice(textareaRef.current.selectionStart);
    const mention = `@${agent.name} `;
    const newValue = before + mention + after;
    setInput(newValue);
    setDropdown(null);
    // Set cursor after mention
    requestAnimationFrame(() => {
      const pos = before.length + mention.length;
      textareaRef.current.selectionStart = pos;
      textareaRef.current.selectionEnd = pos;
      textareaRef.current.focus();
    });
  }

  function selectCommand(cmd) {
    if (!cmd.args) {
      // No args — transform and send immediately
      const message = cmd.transform('');
      setInput('');
      setDropdown(null);
      requestAnimationFrame(() => autoResize());
      onSend(message, []);
    } else {
      // Has args — insert command and let user type args
      setInput(`/${cmd.command} `);
      setDropdown(null);
      requestAnimationFrame(() => {
        const pos = cmd.command.length + 2;
        textareaRef.current.selectionStart = pos;
        textareaRef.current.selectionEnd = pos;
        textareaRef.current.focus();
      });
    }
  }

  function handleKeyDown(e) {
    if (dropdown) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setDropdown(d => ({ ...d, activeIndex: (d.activeIndex + 1) % d.items.length }));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setDropdown(d => ({ ...d, activeIndex: (d.activeIndex - 1 + d.items.length) % d.items.length }));
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        const item = dropdown.items[dropdown.activeIndex];
        if (dropdown.type === 'mention') selectMention(item);
        else selectCommand(item);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setDropdown(null);
        return;
      }
    }

    // Enter without shift — send
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleSend() {
    const text = input.trim();
    if (!text && files.length === 0) return;
    if (disabled) return;

    let finalMessage = text;

    // Check for slash command
    const slashMatch = text.match(/^\/(\w+)\s*([\s\S]*)?$/);
    if (slashMatch) {
      const [, cmd, args] = slashMatch;
      const command = SLASH_COMMANDS.find(c => c.command === cmd);
      if (command) {
        finalMessage = command.transform((args || '').trim());
      }
    }

    onSend(finalMessage, [...files]);
    setInput('');
    setFiles([]);
    setDropdown(null);
    requestAnimationFrame(() => {
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
    });
  }

  function handleFiles(e) {
    setFiles(prev => [...prev, ...Array.from(e.target.files)]);
    e.target.value = '';
  }

  function removeFile(idx) {
    setFiles(prev => prev.filter((_, i) => i !== idx));
  }

  function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length) setFiles(prev => [...prev, ...dropped]);
  }

  return (
    <div className="border-t border-[var(--border)]"
      onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
      onDrop={handleDrop}
    >
      {/* File preview */}
      {files.length > 0 && (
        <div className="px-6 py-2 flex gap-2 flex-wrap border-b border-[var(--border)]">
          {files.map((f, i) => (
            <div key={i} className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] text-xs text-[var(--text-secondary)]">
              {f.type?.startsWith('image/') ? <Image size={12} /> : <FileText size={12} />}
              <span className="max-w-[120px] truncate">{f.name}</span>
              <button onClick={() => removeFile(i)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input area */}
      <div className="relative px-6 py-3 flex items-end gap-3">
        {/* Dropdown */}
        {dropdown && (
          <div ref={dropdownRef}
            className="glass-card absolute bottom-full left-4 right-4 mb-1 max-h-[280px] overflow-y-auto z-50 py-1 rounded-xl">
            {dropdown.type === 'mention' && dropdown.items.map((agent, i) => (
              <button key={agent.name}
                data-active={i === dropdown.activeIndex}
                onMouseDown={e => { e.preventDefault(); selectMention(agent); }}
                onMouseEnter={() => setDropdown(d => ({ ...d, activeIndex: i }))}
                className={`w-full flex items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                  i === dropdown.activeIndex ? 'bg-[var(--bg-hover)]' : ''
                }`}
              >
                {agent.icon ? (
                  <div className="w-6 h-6 rounded flex items-center justify-center"
                    style={{ backgroundColor: `${agent.color}15`, border: `1px solid ${agent.color}30` }}>
                    <agent.icon size={12} style={{ color: agent.color }} />
                  </div>
                ) : (
                  <div className="w-6 h-6 rounded flex items-center justify-center bg-[var(--accent-glow)] border border-[var(--border)]">
                    <span className="text-[10px] mono-heading" style={{ color: agent.color }}>@</span>
                  </div>
                )}
                <span className="mono-heading" style={{ color: agent.color }}>{agent.label}</span>
                {agent.isGroup && <span className="text-[10px] text-[var(--text-muted)] ml-auto">all agents</span>}
              </button>
            ))}
            {dropdown.type === 'command' && dropdown.items.map((cmd, i) => (
              <button key={cmd.command}
                data-active={i === dropdown.activeIndex}
                onMouseDown={e => { e.preventDefault(); selectCommand(cmd); }}
                onMouseEnter={() => setDropdown(d => ({ ...d, activeIndex: i }))}
                className={`w-full flex items-center gap-3 px-3 py-2 text-left text-sm transition-colors ${
                  i === dropdown.activeIndex ? 'bg-[var(--bg-hover)]' : ''
                }`}
              >
                <span className="mono-heading text-[var(--accent)]">/{cmd.command}</span>
                {cmd.args && <span className="text-[var(--text-muted)] text-[11px]">{cmd.args}</span>}
                <span className="ml-auto text-[var(--text-muted)] text-[11px]">{cmd.description}</span>
              </button>
            ))}
          </div>
        )}

        <input type="file" ref={fileRef} onChange={handleFiles} multiple
          accept={fileAccept || "image/*,.pdf,.doc,.docx,.txt,.md,.csv,.json"} className="hidden" />
        <button type="button" onClick={() => fileRef.current?.click()}
          className="pb-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors flex-shrink-0">
          <Paperclip size={16} />
        </button>

        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onClick={e => detectDropdown(input, e.target.selectionStart)}
          placeholder={placeholder || 'type a message...'}
          rows={1}
          disabled={disabled}
          className="flex-1 px-4 py-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] mono-heading text-sm resize-none overflow-y-auto"
          style={{ minHeight: '42px', maxHeight: '200px' }}
        />

        <button
          onClick={handleSend}
          disabled={disabled || (!input.trim() && files.length === 0)}
          className="pb-1 px-3 py-2.5 bg-[var(--accent)] hover:bg-[#60ccf8] text-[var(--bg-deep)] rounded-xl transition-colors disabled:opacity-30 flex-shrink-0"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
});

export default ChatInput;
