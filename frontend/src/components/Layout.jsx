import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { clearSession, post } from '../api';
import { useState, useEffect } from 'react';
import { LayoutGrid, MessageSquare, Users, Brain, RefreshCw, Scale, FileText, FolderOpen, DollarSign, History, Plug, ShieldCheck, Inbox, Settings, Zap, Target, Send, GanttChart, Sun, Moon, PenTool } from 'lucide-react';
import { useNotifications } from './ToastProvider';

const nav = [
  { to: '/', label: 'today', icon: Zap, end: true },
  { to: '/projects', label: 'projects', icon: GanttChart },
  { to: '/deals', label: 'deals', icon: Target },
  { to: '/money', label: 'money', icon: DollarSign },
  { to: '/inbox', label: 'inbox', icon: Inbox, badgeKey: 'inbox_p1p2' },
  { to: '/war-room', label: 'war room', icon: Users },
  { to: '/signatures', label: 'signatures', icon: PenTool },
  { to: '/settings', label: 'settings', icon: Settings },
];

export default function Layout() {
  const navigate = useNavigate();
  const { counts } = useNotifications();
  const [theme, setTheme] = useState(localStorage.getItem('shams_theme') || 'dark');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('shams_theme', theme);
  }, [theme]);

  function toggleTheme() {
    setTheme(t => t === 'dark' ? 'light' : 'dark');
  }

  async function handleLogout() {
    await post('/auth/logout');
    clearSession();
    navigate('/login');
  }

  return (
    <div className="flex h-screen">
      <aside className="w-52 bg-[var(--bg-surface)] border-r border-[var(--border)] flex flex-col">
        <div className="p-5 border-b border-[var(--border)]">
          <h1 className="mono-heading text-xl text-[var(--amber)]">shams</h1>
          <p className="text-[10px] text-[var(--text-muted)] mt-1 uppercase tracking-[0.2em]">mission control</p>
        </div>
        <nav className="flex-1 p-2 space-y-0.5">
          {nav.map(({ to, label, icon: Icon, end, badgeKey }) => {
            const badgeCount = badgeKey ? (counts[badgeKey] || 0) : 0;
            return (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] transition-all duration-200 ${
                    isActive
                      ? 'bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)]'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
                  }`
                }
              >
                <Icon size={14} />
                <span className="mono-heading flex-1">{label}</span>
                {badgeCount > 0 && (
                  <span className="text-[10px] min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-[var(--red)] text-white mono-heading">
                    {badgeCount > 99 ? '99+' : badgeCount}
                  </span>
                )}
              </NavLink>
            );
          })}
        </nav>
        <div className="m-3 flex items-center justify-between">
          <button onClick={toggleTheme}
            className="p-2 text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
          <button onClick={handleLogout}
            className="p-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors mono-heading">
            logout
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto dot-grid">
        <Outlet />
      </main>
    </div>
  );
}
