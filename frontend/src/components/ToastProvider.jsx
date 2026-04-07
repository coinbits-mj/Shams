import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { get, post, getSession } from '../api';
import { CheckCircle, FileText, AlertTriangle, Bell, X, ShieldCheck, LayoutGrid } from 'lucide-react';

const NotificationContext = createContext({ counts: {} });

export function useNotifications() {
  return useContext(NotificationContext);
}

const typeConfig = {
  document_ready: { icon: FileText, color: '#22c55e', label: 'Document Ready' },
  action_pending: { icon: ShieldCheck, color: '#f59e0b', label: 'Action Pending' },
  action_completed: { icon: CheckCircle, color: '#22c55e', label: 'Action Completed' },
  mission_created: { icon: LayoutGrid, color: '#38bdf8', label: 'Mission Created' },
  mission_updated: { icon: LayoutGrid, color: '#38bdf8', label: 'Mission Updated' },
};

const linkRoutes = {
  file: '/files',
  mission: '/missions',
  action: '/actions',
  inbox: '/inbox',
};

export default function ToastProvider({ children }) {
  const [counts, setCounts] = useState({});
  const [toasts, setToasts] = useState([]);
  const [seenIds, setSeenIds] = useState(new Set());

  // Poll counts every 10s (only when authenticated)
  useEffect(() => {
    if (!getSession()) return;
    async function poll() {
      if (!getSession()) return;
      const data = await get('/notifications/counts');
      if (data) setCounts(data);
    }
    poll();
    const i = setInterval(poll, 10000);
    return () => clearInterval(i);
  }, []);

  // Poll for new notifications every 10s (only when authenticated)
  useEffect(() => {
    if (!getSession()) return;
    async function poll() {
      if (!getSession()) return;
      const data = await get('/notifications');
      if (!data) return;
      const newToasts = data.filter(n => !seenIds.has(n.id));
      if (newToasts.length > 0) {
        setToasts(prev => [...newToasts.slice(0, 3), ...prev].slice(0, 5));
        setSeenIds(prev => {
          const next = new Set(prev);
          newToasts.forEach(n => next.add(n.id));
          return next;
        });
      }
    }
    poll();
    const i = setInterval(poll, 10000);
    return () => clearInterval(i);
  }, [seenIds]);

  // Auto-dismiss toasts after 6s
  useEffect(() => {
    if (toasts.length === 0) return;
    const timer = setTimeout(() => {
      setToasts(prev => prev.slice(0, -1));
    }, 6000);
    return () => clearTimeout(timer);
  }, [toasts]);

  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
    post('/notifications/mark-seen', { ids: [id] });
    // Refresh counts
    get('/notifications/counts').then(d => d && setCounts(d));
  }, []);

  const dismissAll = useCallback(() => {
    const ids = toasts.map(t => t.id);
    setToasts([]);
    if (ids.length) {
      post('/notifications/mark-seen', { ids });
      get('/notifications/counts').then(d => d && setCounts(d));
    }
  }, [toasts]);

  return (
    <NotificationContext.Provider value={{ counts, dismissAll }}>
      {children}
      {/* Toast stack */}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map(toast => (
          <Toast key={toast.id} toast={toast} onDismiss={dismissToast} />
        ))}
      </div>
    </NotificationContext.Provider>
  );
}

function Toast({ toast, onDismiss }) {
  const navigate = useNavigate();
  const cfg = typeConfig[toast.event_type] || { icon: Bell, color: '#38bdf8', label: toast.event_type };
  const Icon = cfg.icon;

  function handleClick() {
    const route = linkRoutes[toast.link_type];
    if (route) navigate(route);
    onDismiss(toast.id);
  }

  return (
    <div
      className="glass-card p-3 flex items-start gap-3 cursor-pointer animate-slide-in border-l-2"
      style={{ borderLeftColor: cfg.color }}
      onClick={handleClick}
    >
      <Icon size={16} style={{ color: cfg.color }} className="flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-[var(--text-primary)] font-medium">{toast.title}</p>
        {toast.detail && (
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 truncate">{toast.detail}</p>
        )}
      </div>
      <button
        onClick={e => { e.stopPropagation(); onDismiss(toast.id); }}
        className="text-[var(--text-muted)] hover:text-[var(--text-primary)] flex-shrink-0"
      >
        <X size={12} />
      </button>
    </div>
  );
}
