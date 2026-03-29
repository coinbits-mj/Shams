import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { post, setSession } from '../api';

export default function Login() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [token, setToken] = useState('');
  const navigate = useNavigate();

  // Check if we're returning from a magic link
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

  // Dev mode: direct session input
  async function handleDevLogin(e) {
    e.preventDefault();
    if (token) {
      setSession(token);
      navigate('/');
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl p-8 w-full max-w-md">
        <h1 className="text-2xl font-bold text-amber-400 mb-1">Shams</h1>
        <p className="text-slate-500 text-sm mb-6">Executive AI — Maher Janajri</p>

        {!sent ? (
          <form onSubmit={handleLogin}>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="maher@qcitycoffee.com"
              className="w-full px-4 py-3 bg-slate-800 border border-slate-600 rounded-lg text-white placeholder-slate-500 mb-4 focus:outline-none focus:border-amber-400"
            />
            <button
              type="submit"
              className="w-full py-3 bg-amber-500 hover:bg-amber-400 text-slate-900 font-semibold rounded-lg transition-colors"
            >
              Send Magic Link
            </button>
          </form>
        ) : (
          <div>
            <p className="text-slate-300 mb-4">Check your email for the login link.</p>
            <p className="text-slate-500 text-sm mb-4">Or paste your session token below (dev mode):</p>
            <form onSubmit={handleDevLogin}>
              <input
                type="text"
                value={token}
                onChange={e => setToken(e.target.value)}
                placeholder="Session token"
                className="w-full px-4 py-3 bg-slate-800 border border-slate-600 rounded-lg text-white placeholder-slate-500 mb-4 focus:outline-none focus:border-amber-400"
              />
              <button type="submit" className="w-full py-3 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors">
                Login with Token
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
