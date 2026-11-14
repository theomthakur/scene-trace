import { useEffect, useState } from 'react'
import type { Backend } from '../api'

export const EXTRA_IDS = ['semantic-eval', 'explanation-eval', 'crosscam-eval', 'finetune-development', 'finetune-test', 'benchmark-expansion'] as const
const f2 = (v: unknown) => (typeof v === 'number' ? v.toFixed(2) : v == null ? 'n/a' : String(v))
const pc = (v: unknown) => (typeof v === 'number' ? `${Math.round(v * 100)}%` : 'n/a')

function Card({ label, title, intro, children, limits }: { label: string; title: string; intro: string; children: React.ReactNode; limits?: string[] }) {
  return (
    <section className="eval-card">
      <div className="eval-card-head"><div><p className="eyebrow">{label}</p><h3>{title}</h3><p>{intro}</p></div><span className="eval-badge">RECORDED RESULTS</span></div>
      {children}
      {limits && limits.length > 0 && <details className="eval-details"><summary>Limits and how to read this <span>+</span></summary><div><ul>{limits.map(l => <li key={l}>{l}</li>)}</ul></div></details>}
    </section>
  )
}

function Semantic({ d }: { d: any }) {
  const m = d.metrics
  const rows: [string, any][] = [['Semantic, class words filter first (as the app does)', m.hybrid], ['Semantic, no filter', m.semantic_all], ['Class filter only, in time order', m.class_filter_time]]
  return (
    <Card label="SEARCH · REAL MODEL" title="Semantic search" intro={`${d.queries} labelled queries over ${d.corpus_events} events from two clips. Model: ${d.model.name}.`}
      limits={[d.annotation.caveat, d.reading, 'Similarity is a ranking aid, not a confidence. Recall@k: a query counts as a hit if any relevant event is in the top k.']}>
      <div className="table-scroll" role="region" tabIndex={0} aria-label="Results table, scrolls sideways on small screens"><table><caption className="sr">Semantic search retrieval</caption>
        <thead><tr><th scope="col">Method</th><th scope="col">Recall@1</th><th scope="col">Recall@3</th><th scope="col">Recall@5</th><th scope="col">MRR</th></tr></thead>
        <tbody>{rows.map(([n, r]) => <tr key={n}><th scope="row">{n}</th><td>{pc(r.recall_at_1 ?? r['recall@1'])}</td><td>{pc(r['recall@3'])}</td><td>{pc(r['recall@5'])}</td><td>{f2(r.mrr)}</td></tr>)}
          <tr><th scope="row">Random order (expected rank of first relevant event)</th><td colSpan={4}>{f2(m.random_expected.mean_first_relevant_rank)}</td></tr></tbody></table></div>
      <details className="eval-details"><summary>Per-query results <span>+</span></summary><div><div className="table-scroll" role="region" tabIndex={0} aria-label="Results table, scrolls sideways on small screens"><table><thead><tr><th>Query</th><th>Pool</th><th>First relevant rank (semantic)</th><th>(time order)</th></tr></thead>
        <tbody>{d.per_query.map((q: any) => <tr key={q.query}><th scope="row">{q.query}</th><td>{q.pool_after_class_filter}</td><td>{q.first_relevant_rank.hybrid ?? 'not found'}</td><td>{q.first_relevant_rank.class_filter_time ?? 'not found'}</td></tr>)}</tbody></table></div></div></details>
    </Card>
  )
}

function Explanations({ d }: { d: any }) {
  const v = d.verdicts, a = d.automatic_flags
  return (
    <Card label="EXPLANATIONS · REAL MODEL" title="Video-language descriptions" intro={`${d.rated} descriptions from ${d.model.name}, rated against the frame the model saw.`}
      limits={[d.annotation.caveat, d.reading, `Automatic flags are cheap string checks: they flagged ${a.flagged_and_bad} of ${a.bad_total} bad descriptions and ${a.flagged_but_not_bad} that were not bad.`]}>
      <div className="metric-grid">
        <div><span>MOSTLY SUPPORTED</span><strong>{v.mostly_supported ?? 0}</strong><small>of {d.rated}</small></div>
        <div><span>MIXED</span><strong>{v.mixed ?? 0}</strong><small>some invented detail</small></div>
        <div><span>MOSTLY UNSUPPORTED</span><strong>{v.mostly_unsupported ?? 0}</strong><small>mostly invented</small></div>
        <div><span>INVENTED A DETAIL</span><strong>{d.invented_detail.count}</strong><small>of {d.invented_detail.of}</small></div>
      </div>
      <p className="muted">Said it could not tell: {d.states_uncertainty.count} of {d.states_uncertainty.of}. Mean latency {f2(d.latency_s.mean)} s per description on CPU.</p>
    </Card>
  )
}

function CrossCam({ d }: { d: any }) {
  return (
    <Card label="CROSS-CAMERA · REAL TRACKS" title="Appearance-based association" intro="No multi-camera identity labels exist, so true cross-camera accuracy is not measured. These are negative controls and an upper-bound positive proxy."
      limits={d.limits}>
      {Object.entries(d.clips).map(([name, c]: [string, any]) => (
        <div key={name}><h4>{name} ({c.class}, {c.tracks_used} tracks; {c.covisible_negative_pairs.n} different-object pairs; {c.same_track_halves_positive_proxy.n} same-track pairs)</h4>
          <div className="table-scroll" role="region" tabIndex={0} aria-label="Results table, scrolls sideways on small screens"><table><thead><tr><th scope="col">Similarity threshold</th><th scope="col">Different objects falsely linked</th><th scope="col">Same-track halves linked (upper bound)</th></tr></thead>
            <tbody>{c.by_threshold.map((r: any) => <tr key={r.threshold}><th scope="row">{r.threshold}</th><td>{pc(r.false_match_rate_covisible)} ({r.false_matches})</td><td>{pc(r.same_track_recall_proxy)}</td></tr>)}</tbody></table></div></div>))}
    </Card>
  )
}

function FineTune({ d, id }: { d: any; id: string }) {
  const names = Object.keys(d.splits)
  return (
    <Card label={id === 'finetune-test' ? 'FINE-TUNING · HELD-OUT TEST' : 'FINE-TUNING · DEVELOPMENT'} title="Fine-tuned detector versus pretrained baseline" intro={`Checkpoint ${String(d.checkpoint_sha256).slice(0, 12)}. Trained on the declared-CC0 hard-hat subset on CPU; one seed.`} limits={[d.reading]}>
      {names.map(n => { const s = d.splits[n]; return (
        <div key={n}><h4>{n === 'test' ? 'Held-out test' : 'Validation'}: {s.images} images ({Object.entries(s.boxes).map(([k, v]) => `${v} ${k}`).join(', ')})</h4>
          <div className="table-scroll" role="region" tabIndex={0} aria-label="Results table, scrolls sideways on small screens"><table><thead><tr><th scope="col">Class</th><th scope="col">Fine-tuned AP50</th><th scope="col">Pretrained baseline AP50</th></tr></thead>
            <tbody>{Object.keys(s.finetuned_ap50).map(c => <tr key={c}><th scope="row">{c} ({s.finetuned_ap50[c].n_gt} boxes)</th><td>{f2(s.finetuned_ap50[c].ap)}</td><td>{s.pretrained_baseline_ap50[c].ap == null ? 'cannot detect (not a COCO class)' : f2(s.pretrained_baseline_ap50[c].ap)}</td></tr>)}</tbody></table></div>
          <p className="muted">Person AP50, fine-tuned minus baseline: {f2(s.person_ap50_difference_finetuned_minus_baseline.value)} (95% bootstrap over images: {f2(s.person_ap50_difference_finetuned_minus_baseline.bootstrap_95.low)} to {f2(s.person_ap50_difference_finetuned_minus_baseline.bootstrap_95.high)}).</p></div>) })}
    </Card>
  )
}

function Expansion({ d }: { d: any }) {
  const sets: [string, string, any][] = [['development-2', 'Second development set', d.lanes.development_2], ['test-2', 'Second test set (frozen, run once)', d.lanes.test_2]]
  return (
    <Card label="REAL VIDEO · ADDITIONAL RECORDINGS" title="Expanded benchmark" intro={d.headline} limits={[...(d.limits ?? []), 'A 0.0 false-alert rate on a recording where the detector found nothing is vacuous: check the quality flags.']}>
      {sets.map(([key, title, lane]) => { const n = d.sample_counts[key]; const m = lane.metrics; return (
        <div key={key}><h4>{title}: {n.recordings} recording{n.recordings === 1 ? '' : 's'}, {n.video_seconds} s, {n.annotated_events} annotated event{n.annotated_events === 1 ? '' : 's'}, {n.negative_units} negative unit{n.negative_units === 1 ? '' : 's'}</h4>
          {m ? <>
            <div className="metric-grid">
              <div><span>MATCHED / FALSE / MISSED</span><strong>{m.true_positives} / {m.false_positives} / {m.missed_events}</strong><small>event counts</small></div>
              <div><span>PRECISION</span><strong>{m.precision.value == null ? 'Not defined' : pc(m.precision.value)}</strong><small>{m.precision.value == null ? m.precision.undefined_reason : `${m.precision.numerator} of ${m.precision.denominator}`}</small></div>
              <div><span>RECALL</span><strong>{m.recall.value == null ? 'Not defined' : pc(m.recall.value)}</strong><small>{m.recall.value == null ? m.recall.undefined_reason : `${m.recall.numerator} of ${m.recall.denominator}`}</small></div>
              <div><span>FALSE ALERTS / NEGATIVE HOUR</span><strong>{f2(m.false_alerts_per_negative_video_hour.value)}</strong><small>{m.false_alerts_per_negative_video_hour.false_alerts} over {m.false_alerts_per_negative_video_hour.negative_hours} h</small></div>
            </div>
            <p className="muted">{lane.per_clip.runs.map((r: any) => `${r.clip}: ${r.detections} detections${r.quality_flags.length ? ` (flags: ${r.quality_flags.join(', ')})` : ''}`).join('; ')}</p></> : <p className="empty">Not evaluated. {lane.reason}</p>}
        </div>) })}
    </Card>
  )
}

export default function ExtraEvaluations({ backend, ids }: { backend: Backend; ids: string[] }) {
  const present = EXTRA_IDS.filter(i => ids.includes(i))
  const [data, setData] = useState<Record<string, any>>({}); const [err, setErr] = useState('')
  useEffect(() => { Promise.all(present.map(i => backend.evaluation(i).then(d => [i, d] as const))).then(r => setData(Object.fromEntries(r))).catch(e => setErr(e.message)) }, [backend, ids.join(',')])   // eslint-disable-line react-hooks/exhaustive-deps
  if (present.length === 0) return null
  return (
    <>
      <div className="section-title"><div><p className="eyebrow">02 / ADDITIONAL CAPABILITIES</p><h2>Search, descriptions, association and fine-tuning</h2></div><p>Each is measured on its own, with its own caveats.</p></div>
      {err && <p className="notice err">{err}</p>}
      {data['semantic-eval'] && <Semantic d={data['semantic-eval']} />}
      {data['explanation-eval'] && <Explanations d={data['explanation-eval']} />}
      {data['crosscam-eval'] && <CrossCam d={data['crosscam-eval']} />}
      {data['finetune-development'] && <FineTune d={data['finetune-development']} id="finetune-development" />}
      {data['finetune-test'] && <FineTune d={data['finetune-test']} id="finetune-test" />}
      {data['benchmark-expansion'] && <Expansion d={data['benchmark-expansion']} />}
    </>
  )
}
