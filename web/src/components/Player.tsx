import { useCallback, useEffect, useRef, useState } from 'react'
import type { VideoT, ZoneT } from '../api'
import { contentRect, insideContent, toNormalized, toPixels } from '../geometry'
import { boxesAt, type Obs } from '../observations'

type Idx = { times: number[]; byTime: Map<number, Obs[]> }
const PALETTE = ['#1f5eff', '#b45f06', '#0a7a4a', '#a3195b', '#6d28d9', '#0e7490']

export interface PlayerApi { seek(ms: number): void; el(): HTMLVideoElement | null }

interface Props {
  video: VideoT; src: string | null; idx: Idx; zones: ZoneT[]; showOverlay: boolean; toleranceMs: number
  draftPoints: [number, number][] | null; onDraftPoint: (p: [number, number]) => void; onClosePolygon: () => void
  highlightTracks: number[]; onTime: (ms: number) => void; apiRef: React.MutableRefObject<PlayerApi | null>
}

export default function Player(p: Props) {
  const stage = useRef<HTMLDivElement>(null)
  const vid = useRef<HTMLVideoElement>(null)
  const cvs = useRef<HTMLCanvasElement>(null)
  const [fs, setFs] = useState(false)
  const [rate, setRate] = useState(1)
  const [err, setErr] = useState<string | null>(null)
  const latest = useRef(p); latest.current = p

  const rect = useCallback(() => {
    const s = stage.current!, v = vid.current!
    return contentRect(s.clientWidth, s.clientHeight, v.videoWidth || latest.current.video.width, v.videoHeight || latest.current.video.height)
  }, [])

  const draw = useCallback(() => {
    const c = cvs.current, s = stage.current, v = vid.current
    if (!c || !s || !v) return
    const dpr = window.devicePixelRatio || 1
    const w = s.clientWidth, h = s.clientHeight
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr) }
    const g = c.getContext('2d')!; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h)
    const r = rect(); const q = latest.current
    q.zones.forEach(z => {
      g.beginPath(); z.polygon.forEach(([x, y], i) => { const [px, py] = toPixels(x, y, r); i ? g.lineTo(px, py) : g.moveTo(px, py) }); g.closePath()
      g.fillStyle = z.role === 'restricted' ? 'rgba(31,94,255,0.16)' : 'rgba(180,95,6,0.18)'; g.fill(); g.lineWidth = 2; g.strokeStyle = z.role === 'restricted' ? '#1f5eff' : '#b45f06'; g.stroke()
      const [lx, ly] = toPixels(z.polygon[0][0], z.polygon[0][1], r); g.font = '600 12px system-ui'; g.fillStyle = '#0f1f3d'; g.fillText(z.name, lx + 4, ly + 14)
    })
    if (q.showOverlay) {
      boxesAt(q.idx, v.currentTime * 1000, q.toleranceMs).forEach(o => {
        const [x1, y1] = toPixels(o.box[0], o.box[1], r), [x2, y2] = toPixels(o.box[2], o.box[3], r)
        const hi = q.highlightTracks.includes(o.track_id); g.lineWidth = hi ? 3.5 : 2; g.strokeStyle = PALETTE[o.track_id % PALETTE.length]; g.strokeRect(x1, y1, x2 - x1, y2 - y1)
        if (hi || q.highlightTracks.length === 0) {
          const label = o.class_name
          g.font = '600 11px system-ui'
          const tw = g.measureText(label).width
          g.fillStyle = PALETTE[o.track_id % PALETTE.length]; g.fillRect(x1, Math.max(0, y1 - 15), tw + 8, 15); g.fillStyle = '#fff'; g.fillText(label, x1 + 4, Math.max(11, y1 - 4))
        }
      })
    }
    if (q.draftPoints && q.draftPoints.length) {
      g.beginPath(); q.draftPoints.forEach(([x, y], i) => { const [px, py] = toPixels(x, y, r); i ? g.lineTo(px, py) : g.moveTo(px, py) })
      g.lineWidth = 2; g.setLineDash([6, 4]); g.strokeStyle = '#0f1f3d'; g.stroke(); g.setLineDash([])
      q.draftPoints.forEach(([x, y]) => { const [px, py] = toPixels(x, y, r); g.beginPath(); g.arc(px, py, 4, 0, 7); g.fillStyle = '#fff'; g.fill(); g.strokeStyle = '#0f1f3d'; g.stroke() })
    }
  }, [rect])

  useEffect(() => {
    p.apiRef.current = { seek: ms => { const v = vid.current; if (v) { v.currentTime = Math.max(0, ms / 1000); draw() } }, el: () => vid.current }
  })
  useEffect(() => {
    const v = vid.current!; let raf = 0
    const tick = () => { draw(); latest.current.onTime(v.currentTime * 1000); raf = v.paused ? 0 : requestAnimationFrame(tick) }
    const kick = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(tick) }
    const evs = ['play', 'seeked', 'seeking', 'timeupdate', 'loadeddata', 'pause', 'ratechange'] as const
    evs.forEach(e => v.addEventListener(e, kick))
    const ro = new ResizeObserver(kick); ro.observe(stage.current!)
    const fsc = () => { setFs(document.fullscreenElement === stage.current); kick() }
    document.addEventListener('fullscreenchange', fsc)
    return () => { evs.forEach(e => v.removeEventListener(e, kick)); ro.disconnect(); document.removeEventListener('fullscreenchange', fsc); cancelAnimationFrame(raf) }
  }, [draw])
  useEffect(draw)       // redraw whenever props change (zones, drafts, overlay toggle, highlights)
  useEffect(() => { if (vid.current) vid.current.playbackRate = rate }, [rate])

  const onPointer = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!p.draftPoints) return
    const b = cvs.current!.getBoundingClientRect(); const px = e.clientX - b.left, py = e.clientY - b.top; const r = rect()
    if (!insideContent(px, py, r)) return          // clicks on letterbox bars are ignored
    p.onDraftPoint(toNormalized(px, py, r))
  }
  return (
    <div className="player">
      <div className={`stage${fs ? ' is-fs' : ''}`} ref={stage} style={{ aspectRatio: `${p.video.width} / ${p.video.height}` }}>
        {p.src
          ? <video ref={vid} src={p.src} controls controlsList="nofullscreen" playsInline preload="auto" onError={() => setErr('The browser could not play this video.')} aria-label={`Video: ${p.video.display_name}`} />
          : <video ref={vid} aria-hidden="true" />}
        <canvas ref={cvs} className={p.draftPoints ? 'drawing' : ''} onPointerDown={onPointer} onDoubleClick={() => p.draftPoints && p.draftPoints.length >= 3 && p.onClosePolygon()} aria-label={p.draftPoints ? 'Zone drawing surface. Click to add points, double-click to close.' : 'Detection overlay'} />
        {!p.src && <div className="stage-msg">{p.video.derivative_status === 'failed' ? `Playable version failed: ${p.video.derivative_error ?? ''}` : 'Preparing a browser-playable version...'}</div>}
        {err && <div className="stage-msg err">{err}</div>}
      </div>
      <details className="review-options"><summary>Playback options</summary>
        <div className="player-bar">
          <span className="muted">Speed</span>
          {[0.5, 1, 2].map(r => <button key={r} className={`chip${rate === r ? ' on' : ''}`} aria-pressed={rate === r} onClick={() => setRate(r)}>{r}x</button>)}
          <button className="chip" onClick={() => stage.current?.requestFullscreen?.()}>Fullscreen with overlays</button>
        </div>
      </details>
    </div>
  )
}
