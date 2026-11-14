import { useEffect, useMemo, useState } from 'react'
import { liveBackend, type Backend } from './api'
import { demoBackend } from './demo'
import Review from './views/Review'
import Evaluation from './views/Evaluation'
import SystemDesign from './views/SystemDesign'

const VIEWS = [['review', 'Review'], ['evaluation', 'Evaluation'], ['system-design', 'System Design']] as const
type ViewId = typeof VIEWS[number][0]
const viewFromHash = (): ViewId => (VIEWS.find(([id]) => location.hash.replace('#/', '').startsWith(id))?.[0] ?? 'review')

export default function App() {
  const params = new URLSearchParams(location.search)
  const demo = params.get('mode') === 'demo'
  const backend: Backend = demo ? demoBackend : liveBackend
  const [view, setView] = useState<ViewId>(viewFromHash())
  const [health, setHealth] = useState<'checking' | 'up' | 'down'>(demo ? 'up' : 'checking')
  useEffect(() => { const f = () => setView(viewFromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f) }, [])
  useEffect(() => { document.title = `${VIEWS.find(([id]) => id === view)![1]} - Video Investigation Platform` }, [view])
  useEffect(() => { if (!demo) fetch('/api/health').then(r => setHealth(r.ok ? 'up' : 'down')).catch(() => setHealth('down')) }, [demo])
  const modeBadge = useMemo(() => demo
    ? <span className="badge badge-demo" role="status">Static demo: precomputed results, read only</span>
    : health === 'up' ? <span className="badge badge-live" role="status">Live backend</span>
    : health === 'checking' ? <span className="badge" role="status">Checking backend...</span>
    : <span className="badge badge-err" role="status">Backend offline</span>, [demo, health])

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <div className="brand"><span className="mark" aria-hidden="true" />Video Investigation Platform</div>
        <nav aria-label="Views">
          {VIEWS.map(([id, label]) => <a key={id} href={`#/${id}`} aria-current={view === id ? 'page' : undefined}>{label}</a>)}
        </nav>
        {modeBadge}
      </header>
      <main id="main" tabIndex={-1}>
        {health === 'down' && !demo && <div className="notice err" role="alert">The backend is not reachable. Start it with <code>scripts/dev.sh</code>, or open <a href="?mode=demo">the static demo</a>.</div>}
        {view === 'review' && <Review backend={backend} />}
        {view === 'evaluation' && <Evaluation backend={backend} />}
        {view === 'system-design' && <SystemDesign />}
      </main>
    </>
  )
}
