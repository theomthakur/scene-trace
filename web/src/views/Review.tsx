import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, mediaSrc, type Backend, type EventT, type RunT, type VideoT, type ZoneT } from '../api'
import Player, { type PlayerApi } from '../components/Player'
import Timeline, { fmt } from '../components/Timeline'
import { EventList, EvidenceDrawer } from '../components/EventPanel'
import { groupByTime, type Obs } from '../observations'

const TERMINAL = ['completed', 'failed', 'cancelled', 'interrupted']
const errText = (e: unknown) => e instanceof ApiError ? `${e.message}${e.code && e.code !== 'error' ? ` (${e.code})` : ''}` : (e as Error).message
const rid = () => (crypto.randomUUID?.() ?? String(Math.random()).slice(2))

export default function Review({ backend }: { backend: Backend }) {
  const demo = backend.mode === 'demo'
  const [videos, setVideos] = useState<VideoT[]>([]); const [video, setVideo] = useState<VideoT | null>(null)
  const [zones, setZones] = useState<ZoneT[]>([]); const [zoneVersion, setZoneVersion] = useState<number | null>(null); const [dirty, setDirty] = useState(false)
  const [draft, setDraft] = useState<[number, number][] | null>(null); const [role, setRole] = useState<'restricted' | 'passage'>('restricted'); const [zname, setZname] = useState('')
  const [run, setRun] = useState<RunT | null>(null); const [obs, setObs] = useState<Obs[]>([]); const [events, setEvents] = useState<EventT[]>([]); const [flags, setFlags] = useState<string[]>([])
  const [selected, setSelected] = useState<EventT | null>(null); const [overlay, setOverlay] = useState(true); const [t, setT] = useState(0)
  const [hits, setHits] = useState<Set<string> | null>(null)
  const [notice, setNotice] = useState<{ kind: 'err' | 'info'; text: string } | null>(null)
  const [upl, setUpl] = useState<number | null>(null)
  const [fileName, setFileName] = useState('')
  const player = useRef<PlayerApi | null>(null); const clientReq = useRef(rid())
  const evidence = useRef<HTMLDivElement>(null)

  const fail = (e: unknown) => setNotice({ kind: 'err', text: errText(e) })
  const refreshVideos = useCallback(async () => { try { const v = await backend.listVideos(); setVideos(v); return v } catch (e) { fail(e); return [] } }, [backend])
  useEffect(() => { refreshVideos().then(v => { if (v.length && !video) pick(v[0].id) }) }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  // A completed run is published to the UI only after its observations and events have loaded, so the screen never claims "no events" while they are still in flight.
  const loadRunData = useCallback(async (r: RunT) => {
    if (r.state === 'completed') {
      const [o, e] = await Promise.all([backend.observations(r.id), backend.events(r.id)])
      setObs(o); setEvents(e.events); setFlags(e.quality_flags); setSelected(null); setRun(r)
    } else { setRun(r); setObs([]); setEvents([]); setFlags(r.quality_flags) }
  }, [backend])

  const pick = useCallback(async (id: string) => {
    setNotice(null); setSelected(null); setDraft(null); setRun(null); setObs([]); setEvents([]); setHits(null); setFlags([])
    try {
      const v = await backend.getVideo(id); setVideo(v)
      const z = await backend.getZones(id); setZones(z.zones); setZoneVersion(z.version); setDirty(false)
      const runs = await backend.listRuns(id); const latest = runs.find(r => r.state === 'completed') ?? runs[0] ?? null
      if (latest) await loadRunData(latest); else { setRun(null); setObs([]); setEvents([]) }
    } catch (e) { fail(e) }
  }, [backend, loadRunData])

  // poll the video until its playable version is ready
  useEffect(() => {
    if (!video || video.ready || video.derivative_status === 'failed' || demo) return
    const h = setInterval(async () => { try { setVideo(await backend.getVideo(video.id)) } catch { /* retry */ } }, 1000); return () => clearInterval(h)
  }, [video, backend, demo])
  // poll the run while it is queued or running
  useEffect(() => {
    if (!run || TERMINAL.includes(run.state) || demo) return
    const h = setInterval(async () => { try { const r = await backend.getRun(run.id); if (TERMINAL.includes(r.state)) await loadRunData(r); else setRun(r) } catch (e) { fail(e) } }, 700)
    return () => clearInterval(h)
  }, [run, backend, loadRunData, demo])

  const idx = useMemo(() => groupByTime(obs), [obs])
  const tolerance = useMemo(() => { const ts = idx.times; if (ts.length < 2) return 300; const gaps = ts.slice(1).map((x, i) => x - ts[i]).sort((a, b) => a - b); return Math.round(gaps[Math.floor(gaps.length / 2)] * 1.25) }, [idx])
  const visible = hits ? events.filter(e => hits.has(e.id)) : events
  useEffect(() => {
    if (selected?.id && window.matchMedia('(max-width: 1000px)').matches) {
      evidence.current?.scrollIntoView({ block: 'nearest' })
    }
  }, [selected?.id])

  const upload = async (ev: React.FormEvent<HTMLFormElement>) => {
    ev.preventDefault()
    const form = ev.currentTarget
    const fd = new FormData(form); const f = fd.get('file') as File
    if (!f || !f.size) { setNotice({ kind: 'err', text: 'Choose a video file first.' }); return }
    setNotice(null); setUpl(0)
    try {
      const v = await backend.upload(f, String(fd.get('name') || f.name), setUpl)
      form.reset()
      setFileName('')
      form.closest('details')?.removeAttribute('open')
      await refreshVideos()
      await pick(v.id)
    } catch (e) { fail(e) } finally { setUpl(null) }
  }
  const finishPolygon = () => {
    if (!draft || draft.length < 3) return
    const id = `z${Date.now().toString(36)}`; setZones(z => [...z, { id, name: zname.trim() || `${role === 'restricted' ? 'Restricted' : 'Passage'} ${z.length + 1}`, role, polygon: draft }]); setDraft(null); setZname(''); setDirty(true)
  }
  const undo = () => { if (draft && draft.length) setDraft(draft.slice(0, -1)); else if (zones.length) { setZones(zones.slice(0, -1)); setDirty(true) } }
  const saveZones = async () => { if (!video) return; try { const r = await backend.putZones(video.id, zones); setZones(r.zones); setZoneVersion(r.version); setDirty(false); setNotice({ kind: 'info', text: `Saved zones as version ${r.version}. Editing zones always creates a new version and a new run.` }) } catch (e) { fail(e) } }
  const process = async () => {
    if (!video) return
    try { const r = await backend.createRun(video.id, zoneVersion, clientReq.current); clientReq.current = rid(); setRun(r); setObs([]); setEvents([]); setSelected(null); setNotice(null) } catch (e) { fail(e) }
  }
  const seek = (ms: number) => player.current?.seek(ms)
  const select = (e: EventT) => { setSelected(e); seek(e.start_ms) }
  const changed = (u: EventT) => { setEvents(es => es.map(e => e.id === u.id ? u : e)); setSelected(u) }
  const running = run && !TERMINAL.includes(run.state)
  const reviewing = run?.state === 'completed'

  return (
    <div className="review">
      <div className="workspace-intro">
        <div><h1>{reviewing || demo ? 'Review a video' : 'Analyze a video'}</h1><p>{reviewing || demo ? 'Choose a moment to see what the system flagged and check the video for yourself.' : 'Upload a video, mark an area, then run the analysis.'}</p></div>
      </div>
      {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'err' ? 'alert' : 'status'}>{notice.text} <button className="link" onClick={() => setNotice(null)}>Dismiss</button></div>}
      {!demo && <details className="panel setup-panel recording-options" open={!video}>
        <summary><strong>{video ? 'Switch or upload a video' : 'Choose a video'}</strong></summary>
        <section className="toolbar">
        {videos.length > 1 && <label>Saved videos <select value={video?.id ?? ''} onChange={e => pick(e.target.value)}>{videos.map(v => <option key={v.id} value={v.id}>{v.display_name} ({fmt(v.duration_ms)})</option>)}</select></label>}
        <form className="upload" onSubmit={upload}>
          <label className="file-picker"><span className="file-picker-label">Video file</span><span className="file-picker-button"><span aria-hidden="true">↑</span> {fileName || 'Choose video'}</span><input name="file" type="file" accept="video/*,.mkv,.webm" onChange={e => setFileName(e.target.files?.[0]?.name ?? '')} /></label>
          <label>Name (optional) <input name="name" type="text" maxLength={200} /></label>
          <button className="btn primary" disabled={!fileName || upl !== null}>Upload</button>
          {upl !== null && <progress value={upl} max={1} aria-label="Upload progress" />}
        </form>
        </section>
      </details>}
      {!video && demo && <p className="empty big">Loading the demo video...</p>}
      {video && <div className="grid">
        <div className="col-main">
          <section className="panel player-panel" aria-labelledby="player-h">
            <div className="section-heading"><h2 id="player-h">{video.display_name}</h2><span className="footage-meta">{fmt(video.duration_ms)}</span></div>
            <Player video={video} src={mediaSrc(video.media_url)} idx={idx} zones={zones} showOverlay={overlay} toleranceMs={tolerance} draftPoints={draft} onDraftPoint={p => setDraft(d => [...(d ?? []), p])} onClosePolygon={finishPolygon}
              highlightTracks={selected?.track_ids ?? []} onTime={setT} apiRef={player} />
            <div className="row">
              {reviewing && <label className="check"><input type="checkbox" checked={overlay} onChange={e => setOverlay(e.target.checked)} /> Show boxes around detected objects</label>}
              {zones.length > 0 && <span className="muted">The outlined area is the zone being checked.</span>}
            </div>
            {reviewing && <details className="review-options"><summary>Event timeline</summary>
              <Timeline durationMs={video.duration_ms} events={visible} currentMs={t} selectedId={selected?.id ?? null} onSelect={select} onSeek={seek} />
            </details>}
            {reviewing && <details className="review-options"><summary>Export report</summary><div className="row">
              <a href={backend.reportUrl(run.id, 'html')} target="_blank" rel="noreferrer">HTML</a>
              <a href={backend.reportUrl(run.id, 'markdown')} target="_blank" rel="noreferrer">Markdown</a>
              <a href={backend.reportUrl(run.id, 'json')} target="_blank" rel="noreferrer">JSON</a>
            </div></details>}
          </section>

          {!demo && <details className="panel setup-panel" open={!run}>
            <summary><strong>Mark the area to check</strong><span className="setup-count">{zones.length} {zones.length === 1 ? 'zone' : 'zones'}</span></summary>
          <section aria-labelledby="zones-h">
            <h2 id="zones-h">Scene zones {zoneVersion ? <span className="count">v{zoneVersion}</span> : null}{dirty && <span className="pill flag">unsaved</span>}</h2>
            <p className="muted">Zones use normalized coordinates. A restricted zone tests the bottom-centre of each box (ground contact proxy). A passage zone tests 2D box overlap, not physical clearance.</p>
            <div className="row">
              <fieldset className="inline"><legend className="sr">Zone role</legend>
                {(['restricted', 'passage'] as const).map(r => <label key={r} className="radio"><input type="radio" name="role" checked={role === r} onChange={() => setRole(r)} disabled={demo} /> {r === 'restricted' ? 'Restricted' : 'Passage'}</label>)}</fieldset>
              <label>Name <input value={zname} onChange={e => setZname(e.target.value)} maxLength={80} disabled={demo} /></label>
            </div>
            <div className="row">
              <button className="btn" onClick={() => setDraft(d => d ?? [])} disabled={demo || draft !== null}>Draw zone</button>
              <button className="btn" onClick={finishPolygon} disabled={!draft || draft.length < 3}>Finish polygon</button>
              <button className="btn" onClick={undo} disabled={demo || (!draft?.length && !zones.length)}>Undo</button>
              <button className="btn" onClick={() => setDraft(null)} disabled={!draft}>Cancel drawing</button>
              <button className="btn primary" onClick={saveZones} disabled={demo || !dirty || zones.length === 0}>Save zones</button>
            </div>
            {draft && <p className="notice info" role="status">Drawing: click on the video to add points ({draft.length} so far), double-click or press Finish when there are at least 3.</p>}
            <ul className="zlist">{zones.map(z => <li key={z.id}><span className={`dot ${z.role}`} />{z.name} <span className="muted">({z.role}, {z.polygon.length} points)</span>{!demo && <button className="link" onClick={() => { setZones(zones.filter(x => x.id !== z.id)); setDirty(true) }}>Remove</button>}</li>)}</ul>
          </section>
          </details>}

          {!demo && <details className="panel setup-panel" open={!reviewing}>
            <summary><strong>{reviewing ? 'Analysis settings' : 'Run analysis'}</strong><span className="setup-count">{run?.state ?? 'Not started'}</span></summary>
          <section aria-labelledby="run-h">
            <h2 id="run-h">Processing</h2>
            <div className="row">
              <button className="btn primary" onClick={process} disabled={!!running || zones.length === 0 || dirty || !zoneVersion} title={dirty ? 'Save zones first' : undefined}>{reviewing ? 'Process again' : 'Process video'}</button>
              {running && <button className="btn" onClick={() => backend.cancelRun(run!.id).catch(fail)}>Cancel</button>}
              {run && ['interrupted', 'failed', 'cancelled'].includes(run.state) && !demo && <button className="btn" onClick={() => backend.restartRun(run.id).then(() => backend.getRun(run.id)).then(setRun).catch(fail)}>Restart (new attempt)</button>}
            </div>
            {!run && <p className="muted">{zones.length === 0 ? 'Draw at least one zone and save it before processing.' : 'Ready to process.'}</p>}
            {run && <div className="runinfo" aria-live="polite">
              <p><strong className={`state s-${run.state}`}>{run.state}</strong> (attempt {run.attempt}, zones v{run.zone_version}){run.cancel_requested && run.state === 'running' ? ', cancelling...' : ''}</p>
              {running && <><progress value={run.progress} max={1} aria-label="Processing progress" /><span className="muted"> {Math.round(run.progress * 100)}%, at {fmt(run.processed_ms)}</span></>}
              {run.errors.map((e, i) => <p key={i} className="notice err" role="alert"><strong>{e.code}:</strong> {e.message}{e.retryable ? ' You can restart this run.' : ' This needs a change before it can succeed.'}</p>)}
              {run.state === 'completed' && <p className="muted">{run.timings ? `Processed ${run.timings.sampled_frames} frames in ${run.timings.total_s} s (${run.timings.detect_ms_per_frame} ms/frame detection, ${run.timings.realtime_factor}x real time). ` : ''}Detector: {String(run.detector?.name)} {String(run.detector?.weights)}, device {String(run.detector?.device)}.</p>}
              {run.state === 'completed' && run.quality_flags.length > 0 && <p className="notice warn">Quality flags: {run.quality_flags.join(', ')}. A completed run with these flags may under-report events.</p>}
              {run.state === 'completed' && events.length === 0 && <p className="notice info">No events were found. That is not a certification that the video is incident-free.</p>}
              {flags.length > 0 && run.state !== 'completed' && <p className="muted">Flags: {flags.join(', ')}</p>}
            </div>}
          </section>
          </details>}
        </div>
        <div className="col-side">
          {reviewing && flags.length > 0 && <p className="notice warn">The analysis flagged a quality issue. It may have missed some moments.</p>}
          {reviewing && <EventList events={events} hits={hits} selectedId={selected?.id ?? null} onSelect={select} backend={backend} runId={run.id} onSearchResults={setHits} />}
          {selected && <div ref={evidence}><EvidenceDrawer ev={selected} backend={backend} onSeek={seek} onChanged={changed} readOnly={demo} /></div>}
        </div>
      </div>}
    </div>
  )
}
