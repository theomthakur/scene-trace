import { Fragment, useEffect, useState } from 'react'
import { ApiError, type Backend, type EventT, type SemanticInfo } from '../api'
import { fmt, TYPE_LABEL } from './Timeline'

export const FLAG_TEXT: Record<string, string> = {
  present_at_video_start: 'Already present when the video began, so the true start is unknown.',
  still_active_at_video_end: 'Still active when the video ended, so the true end is unknown.',
  track_lost_while_active: 'The track was lost while active. That does not prove the object left.',
}
const REVIEW_LABEL: Record<string, string> = { unreviewed: 'Unreviewed', confirmed: 'Confirmed', dismissed: 'Dismissed', uncertain: 'Uncertain' }

export function EventList({ events, hits, selectedId, onSelect, backend, runId, onSearchResults }: { events: EventT[]; hits: Set<string> | null; selectedId: string | null; onSelect: (e: EventT) => void; backend: Backend; runId: string; onSearchResults: (ids: Set<string> | null) => void }) {
  const [type, setType] = useState(''); const [status, setStatus] = useState(''); const [q, setQ] = useState('')
  const [note, setNote] = useState<{ understood: string[]; ignored: string[]; notices: string[]; unsupported: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState<'keyword' | 'semantic'>('keyword')
  const [sem, setSem] = useState<Map<string, SemanticInfo> | null>(null)
  const [semNote, setSemNote] = useState<{ kind: 'info' | 'warn' | 'err'; lines: string[]; meaning?: string } | null>(null)
  const matched = events.filter(e => (!hits || hits.has(e.id)) && (!type || e.type === type) && (!status || e.review_status === status))
  const shown = sem ? [...matched].sort((a, b) => (sem.get(a.id)?.rank ?? 1e9) - (sem.get(b.id)?.rank ?? 1e9)) : matched
  const run = async (ev?: React.FormEvent) => {
    ev?.preventDefault()
    if (!q.trim()) { setNote(null); setSem(null); setSemNote(null); onSearchResults(null); return }
    setBusy(true)
    if (mode === 'semantic') {
      setNote(null)
      try {
        const r = await backend.semanticSearch(runId, q, {})
        setSem(new Map(r.results.map(x => [x.id, x.semantic])))
        onSearchResults(new Set(r.results.map(x => x.id)))
        const c = r.structured_constraints_applied
        setSemNote({ kind: r.unsupported ? 'warn' : 'info', meaning: r.score_meaning, lines: [
          ...r.notices,
          ...(c.classes.length || c.event_types.length || c.zone_ids.length ? [`Structured filter applied first: ${[...c.classes, ...c.event_types, ...c.zone_ids].join(', ')}.`] : []),
          ...(!r.unsupported ? [`${r.results.length} event${r.results.length === 1 ? '' : 's'} ranked by embedding similarity${r.candidates_after_structured_filter != null ? ` from ${r.candidates_after_structured_filter} candidates` : ''}.`] : [])] })
      } catch (e) {
        setSem(null); onSearchResults(null)
        setSemNote({ kind: e instanceof ApiError && e.code === 'semantic_unavailable' ? 'warn' : 'err', lines: [(e as Error).message, 'Keyword search and everything else still work.'] })
      } finally { setBusy(false) }
      return
    }
    setSem(null); setSemNote(null)
    try {
      const r = await backend.search(runId, q, {})
      setNote({ understood: r.interpreted.understood, ignored: r.interpreted.ignored_terms, notices: r.notices, unsupported: r.unsupported })
      onSearchResults(new Set(r.results.map(x => x.id)))
    } finally { setBusy(false) }
  }
  useEffect(() => { setQ(''); setNote(null); setSem(null); setSemNote(null); onSearchResults(null) }, [runId])   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section aria-labelledby="events-h" className="panel event-panel">
      <div className="section-heading"><div><p className="eyebrow">ANALYSIS</p><h2 id="events-h">Detected events <span className="count">{shown.length}</span></h2></div></div>
      <p className="panel-description">Select an event to inspect its timeline and supporting frames.</p>
      <form className="search" onSubmit={run} role="search">
        <label className="sr" htmlFor="q">Search events</label>
        <input id="q" value={q} onChange={e => setQ(e.target.value)} placeholder={mode === 'semantic' ? 'Describe what you are looking for, for example "red car"' : 'Search events or time...'} />
        <button className="btn" disabled={busy}>{busy ? 'Searching...' : 'Search'}</button>
      </form>
      <div className="segmented" role="radiogroup" aria-label="Search mode">
        {(['keyword', 'semantic'] as const).map(m => <label key={m} className={mode === m ? 'on' : ''}><input type="radio" name="searchmode" checked={mode === m} onChange={() => { setMode(m); setSem(null); setSemNote(null); setNote(null); onSearchResults(null) }} />{m === 'keyword' ? 'Keyword' : 'Semantic'}</label>)}
      </div>
      {semNote && <div className={`notice ${semNote.kind}`} role="status">
        {semNote.lines.map(l => <p key={l}>{l}</p>)}
        {semNote.meaning && <p className="muted"><strong>About the score:</strong> {semNote.meaning}</p>}
      </div>}
      {note && <div className={`notice ${note.unsupported ? 'warn' : 'info'}`} role="status">
        {note.understood.length > 0 && <p><strong>Understood:</strong> {note.understood.join('; ')}</p>}
        {note.ignored.length > 0 && <p><strong>Ignored words:</strong> {note.ignored.join(', ')}</p>}
        {note.notices.map(n => <p key={n}>{n}</p>)}
        <p className="muted">This is a transparent keyword parser, not a language model, and results are ordered by time with no relevance score.</p>
      </div>}
      <div className="filters">
        <label>Type <select value={type} onChange={e => setType(e.target.value)}><option value="">All</option>{Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label>Review <select value={status} onChange={e => setStatus(e.target.value)}><option value="">All</option>{Object.entries(REVIEW_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
      </div>
      {shown.length === 0 && <p className="empty">{hits ? 'No events match this search.' : 'No events match. A run with no events is not proof the video is incident-free; check the quality flags.'}</p>}
      <ul className="events">
        {shown.map(e => (
          <li key={e.id}><button className={`ev${selectedId === e.id ? ' sel' : ''}`} aria-current={selectedId === e.id ? 'true' : undefined} onClick={() => onSelect(e)}>
            <span className="ev-title">{TYPE_LABEL[e.type]}: {e.class_name} #{e.track_ids.join(', #')}</span>
            <span className="ev-time">{fmt(e.start_ms)} to {fmt(e.end_ms)}</span>
            {sem?.get(e.id) && <span className="pill sem" title="Cosine similarity between the query and this event's best evidence image. A ranking aid, not a confidence.">#{sem.get(e.id)!.rank} similarity {sem.get(e.id)!.similarity.toFixed(2)}</span>}
            {sem?.get(e.id) && <span className="muted ev-sem">best match: {sem.get(e.id)!.best_item.kind === 'crop' ? 'crop of the tracked object' : 'full frame'}, {sem.get(e.id)!.best_item.role} frame at {fmt(sem.get(e.id)!.best_item.t_ms)}</span>}
            <span className={`pill st-${e.review_status}`}>{REVIEW_LABEL[e.review_status]}</span>
            {e.uncertainty_flags.length > 0 && <span className="pill flag">{e.uncertainty_flags.length} flag{e.uncertainty_flags.length > 1 ? 's' : ''}</span>}
            {e.source === 'fixture' && <span className="pill flag">fixture</span>}
          </button></li>))}
      </ul>
    </section>
  )
}

export function EvidenceDrawer({ ev, backend, onSeek, onChanged, readOnly }: { ev: EventT | null; backend: Backend; onSeek: (ms: number) => void; onChanged: (e: EventT) => void; readOnly: boolean }) {
  const [verdict, setVerdict] = useState<'confirmed' | 'dismissed' | 'uncertain'>('confirmed'); const [note, setNote] = useState('')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null); const [orig, setOrig] = useState(false); const [saving, setSaving] = useState(false)
  // Sync the form with the event. The status message is cleared only when a different event is selected, so "Saved." survives the version bump caused by saving.
  useEffect(() => { setNote(ev?.review_note ?? ''); setVerdict(ev && ev.review_status !== 'unreviewed' ? ev.review_status : 'confirmed') }, [ev?.id, ev?.review_version])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setMsg(null) }, [ev?.id])
  if (!ev) return <section className="panel" aria-labelledby="ev-h"><h2 id="ev-h">Evidence</h2><p className="empty">Select an event to see its evidence.</p></section>
  const save = async () => {
    setSaving(true); setMsg(null)
    try { const u = await backend.review(ev.id, verdict, note, ev.review_version); onChanged(u); setMsg({ kind: 'ok', text: 'Saved.' }) }
    catch (e) { setMsg({ kind: 'err', text: e instanceof ApiError && e.status === 409 ? 'This event changed elsewhere. Reload the events and review again.' : (e as Error).message }) }
    finally { setSaving(false) }
  }
  return (
    <section className="panel" aria-labelledby="ev-h">
      <h2 id="ev-h">Evidence</h2>
      <p className="ev-desc">{ev.description}</p>
      <dl className="kv">
        <dt>Interval</dt><dd>{fmt(ev.start_ms)} to {fmt(ev.end_ms)} ({ev.start_ms} to {ev.end_ms} ms)</dd>
        <dt>Rule</dt><dd>{String(ev.details.rule)} <span className="muted">({ev.rule_version})</span></dd>
        {Object.entries(ev.details).filter(([k]) => !['rule', 'zone_name', 'assumption', 'person_association'].includes(k)).map(([k, v]) => <Fragment key={k}><dt>{k.replaceAll('_', ' ')}</dt><dd>{String(v)}</dd></Fragment>)}
        {ev.details.assumption != null && <><dt>Assumption</dt><dd>{String(ev.details.assumption)}</dd></>}
        {ev.details.person_association != null && <><dt>Person association</dt><dd>{String(ev.details.person_association)}</dd></>}
        <dt>Source</dt><dd>{ev.source === 'detector' ? 'Real detector output on decoded video pixels' : 'FIXTURE: scripted detections, not real inference'}</dd>
      </dl>
      {ev.uncertainty_flags.length > 0 && <ul className="flags">{ev.uncertainty_flags.map(f => <li key={f}><strong>{f.replaceAll('_', ' ')}.</strong> {FLAG_TEXT[f] ?? ''}</li>)}</ul>}
      <h3>Evidence frames</h3>
      <label className="check"><input type="checkbox" checked={orig} onChange={e => setOrig(e.target.checked)} /> Show unannotated originals</label>
      <div className="frames">
        {ev.evidence.frames.map(f => f.missing ? <div key={f.role} className="frame missing">{f.role}: frame unavailable</div> :
          <button key={f.role} className="frame" onClick={() => onSeek(f.t_ms)} aria-label={`${f.role} frame at ${fmt(f.t_ms)}. Jump to this time.`}>
            <img src={backend.evidenceUrl(ev, `${f.role}${orig ? '_original' : ''}.jpg`)} alt={`${f.role} of event, ${orig ? 'original' : 'with boxes'}`} loading="lazy" /><span>{f.role} {fmt(f.t_ms)}</span></button>)}
      </div>
      {ev.evidence.clip && <><h3>Context clip <span className="muted">{fmt(ev.evidence.clip_range_ms[0])} to {fmt(ev.evidence.clip_range_ms[1])}</span></h3><video className="clip" controls preload="none" src={backend.evidenceUrl(ev, 'clip.mp4')} /></>}
      {ev.evidence.clip_error && <p className="notice warn">Clip unavailable: {ev.evidence.clip_error}</p>}
      <h3>Review</h3>
      <fieldset disabled={readOnly || saving}>
        <legend className="sr">Verdict</legend>
        {(['confirmed', 'dismissed', 'uncertain'] as const).map(v => <label key={v} className="radio"><input type="radio" name="verdict" checked={verdict === v} onChange={() => setVerdict(v)} /> {REVIEW_LABEL[v]}</label>)}
        <label className="block">Note<textarea value={note} onChange={e => setNote(e.target.value)} rows={3} maxLength={2000} /></label>
        <button className="btn primary" onClick={save}>Save review</button>
      </fieldset>
      {readOnly && <p className="muted">Static demo: reviews are not saved.</p>}
      {msg && <p className={`notice ${msg.kind === 'ok' ? 'info' : 'err'}`} role="status">{msg.text}</p>}
      <p className="muted">Current: {REVIEW_LABEL[ev.review_status]} (revision {ev.review_version}){ev.reviewed_at ? `, ${ev.reviewed_at}` : ''}</p>
    </section>
  )
}
