import { useEffect, useMemo, useState } from 'react'
import { API_BASE, liveBackend, type Backend } from './api'
import { demoBackend } from './demo'
import Review from './views/Review'
import Evaluation from './views/Evaluation'
import SystemDesign from './views/SystemDesign'

const VIEWS = [['review', 'Review'], ['evaluation', 'Evaluation'], ['system-design', 'System Design']] as const
type ViewId = typeof VIEWS[number][0]
const viewFromHash = (): ViewId => (VIEWS.find(([id]) => location.hash.replace('#/', '').startsWith(id))?.[0] ?? 'review')

export default function App() {
  const params = new URLSearchParams(location.search)
  const demo = (params.get('mode') ?? (import.meta.env.VITE_DEFAULT_MODE as string | undefined)) === 'demo'
  const backend: Backend = demo ? demoBackend : liveBackend
  const [view, setView] = useState<ViewId>(viewFromHash())
  const [health, setHealth] = useState<'checking' | 'up' | 'down'>(demo ? 'up' : 'checking')
  const [auth, setAuth] = useState<{ required: boolean; authenticated: boolean } | null>(null)
  const [token, setToken] = useState(''); const [authErr, setAuthErr] = useState('')
  const canRead = demo || auth?.authenticated
  useEffect(() => { const f = () => setView(viewFromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f) }, [])
  useEffect(() => { document.title = `${VIEWS.find(([id]) => id === view)![1]} | SceneTrace` }, [view])
  useEffect(() => { if (!demo) fetch(`${API_BASE}/api/health`).then(r => setHealth(r.ok ? 'up' : 'down')).catch(() => setHealth('down')) }, [demo])
  useEffect(() => {
    if (!demo) fetch(`${API_BASE}/api/session`, { credentials: 'include' })
      .then(r => { if (!r.ok) throw new Error('Session unavailable'); return r.json() })
      .then(setAuth).catch(() => setAuthErr('Could not check the server session. Reload to try again.'))
  }, [demo])
  const login = async (e: React.FormEvent) => {
    e.preventDefault(); setAuthErr('')
    const r = await fetch(`${API_BASE}/api/session`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) })
    if (r.ok) location.reload(); else setAuthErr('That access token was not accepted.')
  }
  const modeBadge = useMemo(() => demo
    ? <span className="badge badge-demo" role="status">Static demo: precomputed results, read only</span>
    : health === 'up' ? <span className="badge badge-live" role="status">Live backend</span>
    : health === 'checking' ? <span className="badge" role="status">Checking backend...</span>
    : <span className="badge badge-err" role="status">Backend offline</span>, [demo, health])

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <div className="brand"><span className="mark" aria-hidden="true"><span /></span><span>SceneTrace <small>VIDEO INTELLIGENCE</small></span></div>
        <nav aria-label="Views">
          {VIEWS.map(([id, label]) => <a key={id} href={`#/${id}`} aria-current={view === id ? 'page' : undefined}>{label}</a>)}
        </nav>
        {modeBadge}
      </header>
      <main id="main" tabIndex={-1}>
        {!demo && auth?.required && !auth.authenticated && (
          <form className="panel login" onSubmit={login} aria-labelledby="login-h">
            <h2 id="login-h">Access token required</h2>
            <p className="muted">This SceneTrace server is protected. Enter the access token its operator gave you.</p>
            <label>Access token <input type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" /></label>
            <button className="btn primary" disabled={!token}>Continue</button>
            {authErr && <p className="notice err" role="alert">{authErr}</p>}
          </form>)}
        {health === 'down' && !demo && <div className="notice err" role="alert">The backend is not reachable. Start it with <code>scripts/dev.sh</code>, or open <a href="?mode=demo">the static demo</a>.</div>}
        {!auth && !demo && health !== 'down' && authErr && <p className="notice err" role="alert">{authErr}</p>}
        {canRead && view === 'review' && <Review backend={backend} />}
        {canRead && view === 'evaluation' && <Evaluation backend={backend} />}
        {view === 'system-design' && <SystemDesign />}
      </main>
    </>
  )
}
