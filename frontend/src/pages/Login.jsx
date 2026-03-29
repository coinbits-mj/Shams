import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { post, setSession } from '../api';

export default function Login() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [token, setToken] = useState('');
  const navigate = useNavigate();

  const params = new URLSearchParams(window.location.search);
  const verifyToken = params.get('token');

  if (verifyToken && !sent) {
    fetch(`/api/auth/verify?token=${verifyToken}`)
      .then(r => r.json())
      .then(data => {
        if (data.session) {
          setSession(data.session);
          navigate('/');
        }
      });
  }

  async function handleLogin(e) {
    e.preventDefault();
    await post('/auth/login', { email });
    setSent(true);
  }

  async function handleDevLogin(e) {
    e.preventDefault();
    if (token) { setSession(token); navigate('/'); }
  }

  return (
    <div className="min-h-screen flex items-center justify-center dot-grid">
      <div className="glass-card p-8 w-full max-w-sm">
        <h1 className="mono-heading text-2xl text-[var(--amber)] mb-1">shams</h1>
        <p className="text-[10px] text-[var(--text-muted)] mb-8 uppercase tracking-[0.2em]">executive intelligence</p>

        {!sent ? (
          <form onSubmit={handleLogin}>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="email"
              className="w-full px-4 py-3 bg-[var(--bg-deep)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] placeholder-[var(--text-muted)] mb-4 focus:outline-none focus:border-[var(--accent)] mono-heading text-sm" />
            <button type="submit"
              className="w-full py-3 bg-[var(--accent)] hover:bg-[#60ccf8] text-[var(--bg-deep)] font-semibold rounded-lg transition-colors mono-heading text-sm">
              send magic link
            </button>
          </form>
        ) : (
          <div>
            <p className="text-[var(--text-secondary)] text-sm mb-4">check your email for the login link.</p>
            <form onSubmit={handleDevLogin}>
              <input type="text" value={token} onChange={e => setToken(e.target.value)}
                placeholder="or paste session token"
                className="w-full px-4 py-3 bg-[var(--bg-deep)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] placeholder-[var(--text-muted)] mb-4 focus:outline-none focus:border-[var(--accent)] mono-heading text-sm" />
              <button type="submit"
                className="w-full py-3 bg-[var(--bg-card)] hover:bg-[var(--bg-hover)] text-[var(--text-primary)] rounded-lg transition-colors mono-heading text-sm border border-[var(--border)]">
                enter
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
