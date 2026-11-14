import { useEffect, useState } from 'react'
import type { Backend } from '../api'

type Ratio = { value: number | null; numerator: number; denominator: number; undefined_reason: string | null }
const pct = (r?: Ratio) => !r ? 'Not evaluated' : r.value === null ? 'Not defined' : `${(r.value * 100).toFixed(0)}%`
const count = (r?: Ratio) => !r ? '' : r.value === null ? r.undefined_reason : `${r.numerator} of ${r.denominator} events`

function Lane({ title, label, lane }: { title: string; label: string; lane: any }) {
  if (!lane || lane.status === 'not_evaluated') return <section className="eval-card"><p className="eyebrow">{label}</p><h3>{title}</h3><p>Not evaluated. {lane?.reason ?? ''}</p></section>
  const m = lane.metrics, b = lane.baseline_no_persistence?.metrics
  return <section className="eval-card"><div className="eval-card-head"><div><p className="eyebrow">{label}</p><h3>{title}</h3><p>{lane.scope}</p></div><span className="eval-badge">RECORDED RESULTS</span></div>
    <div className="metric-grid"><div><span>PRECISION</span><strong>{pct(m.precision)}</strong><small>{count(m.precision)}</small></div><div><span>RECALL</span><strong>{pct(m.recall)}</strong><small>{count(m.recall)}</small></div><div><span>MATCHED / FALSE / MISSED</span><strong>{m.true_positives} / {m.false_positives} / {m.missed_events}</strong><small>Event counts</small></div><div><span>MEAN ONSET ERROR</span><strong>{m.onset_abs_error_ms_mean === null ? '—' : `${Math.round(m.onset_abs_error_ms_mean)} ms`}</strong><small>{m.onset_matched_count} matched events</small></div></div>
    <details className="eval-details"><summary>See methodology and detailed results <span>+</span></summary><div><p>False alerts per negative-video hour: {m.false_alerts_per_negative_video_hour.value === null ? `undefined (${m.false_alerts_per_negative_video_hour.undefined_reason})` : `${m.false_alerts_per_negative_video_hour.value.toFixed(1)} (${m.false_alerts_per_negative_video_hour.false_alerts} alerts over ${m.false_alerts_per_negative_video_hour.negative_hours} h)`}.</p>{b && <p>Without persistence: {b.true_positives} matched, {b.false_positives} false positives, {b.missed_events} missed. Precision {pct(b.precision)}; recall {pct(b.recall)}.</p>}{lane.notes?.map((n: string) => <p key={n}>{n}</p>)}{lane.per_clip && <details><summary>Per-clip data</summary><pre>{JSON.stringify(lane.per_clip, null, 2)}</pre></details>}</div></details>
  </section>
}

export default function Evaluation({ backend }: { backend: Backend }) {
  const [ids, setIds] = useState<string[] | null>(null); const [sel, setSel] = useState(''); const [ev, setEv] = useState<any>(null); const [err, setErr] = useState('')
  useEffect(() => { backend.evaluations().then(i => { setIds(i); if (i.length) setSel(i[i.length - 1]) }).catch(e => setErr(e.message)) }, [backend])
  useEffect(() => { if (sel) backend.evaluation(sel).then(setEv).catch(e => setErr(e.message)) }, [sel, backend])
  if (err) return <p className="notice err">{err}</p>
  if (ids && ids.length === 0) return <div className="story-page"><h1>Evaluation</h1><p className="empty big">No evaluation report is available yet.</p></div>
  if (!ev) return <p className="empty big">Loading evaluation...</p>
  return <div className="story-page evaluation-page"><header className="story-hero"><div><p className="eyebrow">MEASURING THE SYSTEM <span> / </span> EVALUATION</p><h1>Results with<br /><em>the full context.</em></h1><p>{ev.headline}</p></div><div className="hero-index"><span>OUR APPROACH</span><strong>Measure clearly.<br />Show the limits.</strong><small>Results from saved evaluation artifacts</small></div></header>
    {ids && ids.length > 1 && <label>Report <select value={sel} onChange={e => setSel(e.target.value)}>{ids.map(i => <option key={i}>{i}</option>)}</select></label>}
    <div className="scope-callout"><span aria-hidden="true">i</span><div><strong>How to read these results</strong><p>{ev.scope_warning}</p></div></div>
    <div className="section-title"><div><p className="eyebrow">01 / RESULTS</p><h2>From rules to real footage</h2></div><p>Each dataset is shown separately.</p></div>
    <Lane title="Algorithm fixtures" label="GENERATED TRAJECTORIES · NO DETECTOR" lane={ev.lanes.fixture} />
    <Lane title="Development footage" label="REAL VIDEO · DEVELOPMENT" lane={ev.lanes.development} />
    <Lane title="Frozen test footage" label="REAL VIDEO · TEST" lane={ev.lanes.test} />
    <details className="technical-details"><summary>Evaluation details and what remains unmeasured <span>+</span></summary><div><p><strong>Annotation:</strong> {ev.annotation.method} ({ev.annotation.reviewers} reviewer; not expert consensus). <strong>Hardware:</strong> {ev.hardware}.</p><p>Detection mAP and tracking metrics have not been measured against ground-truth boxes or tracks.</p><ul>{ev.not_measured.map((n: string) => <li key={n}>{n}</li>)}</ul><p><strong>Sampling-rate sweep:</strong> {ev.sweep_note}</p>{ev.sweep && <table><thead><tr><th>Sampling</th><th>Tracks</th><th>Detections</th><th>Events</th><th>Seconds</th></tr></thead><tbody>{ev.sweep.map((s: any) => <tr key={s.label}><th>{s.label}</th><td>{s.tracks}</td><td>{s.detections}</td><td>{s.events}</td><td>{s.total_s}</td></tr>)}</tbody></table>}<p>Config hash: <code>{ev.config_hash}</code><br />Manifest hash: <code>{ev.manifest_sha256}</code><br />Generated: {ev.generated_at}</p></div></details>
  </div>
}
