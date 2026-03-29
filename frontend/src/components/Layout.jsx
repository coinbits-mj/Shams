import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { clearSession, post } from '../api';
import { MessageSquare, Brain, RefreshCw, Scale, FileText, FolderOpen, Landmark, History } from 'lucide-react';

const nav = [
  { to: '/chat', label: 'Chat', icon: MessageSquare },
  { to: '/conversations', label: 'History', icon: History },
  { to: '/memory', label: 'Memory', icon: Brain },
  { to: '/loops', label: 'Open Loops', icon: RefreshCw },
  { to: '/decisions', label: 'Decisions', icon: Scale },
  { to: '/briefings', label: 'Briefings', icon: FileText },
  { to: '/files', label: 'Files', icon: FolderOpen },
  { to: '/mercury', label: 'Mercury', icon: Landmark },
];

export default function Layout() {
  const navigate = useNavigate();

  async function handleLogout() {
    await post('/auth/logout');
    clearSession();
    navigate('/login');
  }

  return (
    <div className="flex h-screen">
      <aside className="w-56 bg-slate-900 border-r border-slate-700 flex flex-col">
        <div className="p-4 border-b border-slate-700">
          <h1 className="text-xl font-bold text-amber-400">☀ Shams</h1>
          <p className="text-xs text-slate-500 mt-1">Executive AI</p>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <button
          onClick={handleLogout}
          className="m-2 p-2 text-xs text-slate-500 hover:text-slate-300 transition-colors"
        >
          Logout
        </button>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
