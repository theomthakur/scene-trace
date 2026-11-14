import { useEffect, useState } from 'react'
import type { Backend } from '../api'

type Ratio = { value: number | null; numerator: number; denominator: number; undefined_reason: string | null }
const pct = (r?: Ratio) => !r ? 'not evaluated' : r.value === null ? `undefined (${r.undefined_reason})` : `${(r.value * 100).toFixed(0)}% (${r.numerator}/${r.denominator})`

function Lane({ title, lane }: { title: string; lane: any }) {
  if (!lane || lane.status === 'not_evaluated') return <section className="panel"><h3>{title}</h3><p className="empty">Not evaluated. {lane?.reason ?? ''}</p></section>
  const m = lane.metrics, b = lane.baseline_no_persistence?.metrics
  return (
    <section className="panel">
      <h3>{title}</h3>
      <p className="muted">{lane.scope}</p>
      <table>
        <caption className="sr">{title} metrics</caption>
        <thead><tr><th scope="col">Measure</th><th scope="col">Temporal rules (default)</th>{b && <th scope="col">No-persistence baseline</th>}</tr></thead>
        <tbody>
          <tr><th scope="row">True positives / false positives / missed</th><td>{m.true_positives} / {m.false_positives} / {m.missed_events}</td>{b && <td>{b.true_positives} / {b.false_positives} / {b.missed_events}</td>}</tr>
          <tr><th scope="row">Precision</th><td>{pct(m.precision)}</td>{b && <td>{pct(b.precision)}</td>}</tr>
          <tr><th scope="row">Recall</th><td>{pct(m.recall)}</td>{b && <td>{pct(b.recall)}</td>}</tr>
          <tr><th scope="row">False alerts per negative-video hour</th><td>{m.false_alerts_per_negative_video_hour.value === null ? `undefined (${m.false_alerts_per_negative_video_hour.undefined_reason})` : `${m.false_alerts_per_negative_video_hour.value.toFixed(1)} (${m.false_alerts_per_negative_video_hour.false_alerts} alerts over ${m.false_alerts_per_negative_video_hour.negative_hours} h)`}</td>{b && <td>{b.false_alerts_per_negative_video_hour.value === null ? 'undefined' : b.false_alerts_per_negative_video_hour.value.toFixed(1)}</td>}</tr>
          <tr><th scope="row">Mean onset error</th><td>{m.onset_abs_error_ms_mean === null ? 'no matched events' : `${Math.round(m.onset_abs_error_ms_mean)} ms (${m.onset_matched_count} matched)`}</td>{b && <td>{b.onset_abs_error_ms_mean === null ? 'no matched events' : `${Math.round(b.onset_abs_error_ms_mean)} ms`}</td>}</tr>
        </tbody>
      </table>
      {lane.per_clip && <details><summary>Per-clip results and failure cases</summary><pre>{JSON.stringify(lane.per_clip, null, 2)}</pre></details>}
      {lane.notes?.map((n: string) => <p key={n} className="muted">{n}</p>)}
    </section>
  )
}

export default function Evaluation({ backend }: { backend: Backend }) {
  const [ids, setIds] = useState<string[] | null>(null); const [sel, setSel] = useState(''); const [ev, setEv] = useState<any>(null); const [err, setErr] = useState('')
  useEffect(() => { backend.evaluations().then(i => { setIds(i); if (i.length) setSel(i[i.length - 1]) }).catch(e => setErr(e.message)) }, [backend])
  useEffect(() => { if (sel) backend.evaluation(sel).then(setEv).catch(e => setErr(e.message)) }, [sel, backend])
  if (err) return <p className="notice err">{err}</p>
  if (ids && ids.length === 0) return <div className="doc"><h1>Evaluation</h1><p className="empty big">Not evaluated. Run <code>python -m video_investigator.cli evaluate</code> to produce measured results.</p></div>
  if (!ev) return <p className="empty big">Loading...</p>
  return (
    <div className="doc wide">
      <h1>Evaluation</h1>
      {ids && ids.length > 1 && <label>Report <select value={sel} onChange={e => setSel(e.target.value)}>{ids.map(i => <option key={i}>{i}</option>)}</select></label>}
      <p className="lead">{ev.headline}</p>
      <dl className="kv">
        <dt>Config hash</dt><dd><code>{ev.config_hash}</code></dd><dt>Manifest hash</dt><dd><code>{ev.manifest_sha256}</code></dd><dt>Generated</dt><dd>{ev.generated_at}</dd>
        <dt>Annotation</dt><dd>{ev.annotation.method} ({ev.annotation.reviewers} reviewer; not expert consensus)</dd><dt>Hardware</dt><dd>{ev.hardware}</dd>
      </dl>
      <div className="notice warn"><strong>Read this first.</strong> {ev.scope_warning}</div>
      <Lane title="Algorithm fixtures (generated trajectories, no detector)" lane={ev.lanes.fixture} />
      <Lane title="Real footage: development split" lane={ev.lanes.development} />
      <Lane title="Real footage: frozen test split" lane={ev.lanes.test} />
      <section className="panel"><h3>Detection and tracking</h3><p className="empty">Not evaluated: no ground-truth boxes or tracks were annotated, so detection mAP and tracking metrics are not reported.</p></section>
      <section className="panel"><h3>Sampling-rate sweep (development clips only)</h3>
        {ev.sweep ? <table><thead><tr><th scope="col">Sampling</th><th scope="col">Tracks</th><th scope="col">Detections</th><th scope="col">Events</th><th scope="col">Seconds to process</th></tr></thead><tbody>{ev.sweep.map((s: any) => <tr key={s.label}><th scope="row">{s.label}</th><td>{s.tracks}</td><td>{s.detections}</td><td>{s.events}</td><td>{s.total_s}</td></tr>)}</tbody></table> : <p className="empty">Not evaluated.</p>}
        <p className="muted">{ev.sweep_note}</p></section>
      <section className="panel"><h3>Unsupported or not measured</h3><ul>{ev.not_measured.map((n: string) => <li key={n}>{n}</li>)}</ul></section>
    </div>
  )
}
