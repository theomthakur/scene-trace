import type { EventT } from '../api'

export const TYPE_LABEL: Record<string, string> = { zone_entry: 'Zone entry', stationary_object: 'Stationary', passage_occupancy: 'Aisle occupancy' }
export const fmt = (ms: number) => { const s = ms / 1000; return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}` }

interface Props { durationMs: number; events: EventT[]; currentMs: number; selectedId: string | null; onSelect: (e: EventT) => void; onSeek: (ms: number) => void }

export default function Timeline({ durationMs, events, currentMs, selectedId, onSelect, onSeek }: Props) {
  const pct = (ms: number) => `${Math.min(100, Math.max(0, (ms / Math.max(1, durationMs)) * 100))}%`
  const lanes: EventT[][] = []
  events.forEach(e => { const lane = lanes.find(l => l.every(o => o.end_ms < e.start_ms || o.start_ms > e.end_ms)); if (lane) lane.push(e); else lanes.push([e]) })
  const onKey = (ev: React.KeyboardEvent) => {
    if (ev.key === 'ArrowLeft') { ev.preventDefault(); onSeek(currentMs - 1000) } else if (ev.key === 'ArrowRight') { ev.preventDefault(); onSeek(currentMs + 1000) }
  }
  return (
    <div className="timeline">
      <div className="tl-axis" role="slider" tabIndex={0} aria-label="Video position. Left and right arrows move one second." aria-valuemin={0} aria-valuemax={Math.round(durationMs / 1000)} aria-valuenow={Math.round(currentMs / 1000)} aria-valuetext={fmt(currentMs)}
        onKeyDown={onKey} onClick={e => { const b = e.currentTarget.getBoundingClientRect(); onSeek(((e.clientX - b.left) / b.width) * durationMs) }}>
        <div className="tl-playhead" style={{ left: pct(currentMs) }} />
        {events.length === 0 && <span className="tl-empty">No events on the timeline</span>}
      </div>
      <div className="tl-lanes" style={{ minHeight: Math.max(1, lanes.length) * 30 }}>
        {lanes.map((lane, i) => lane.map(e => (
          <button key={e.id} className={`tl-seg st-${e.review_status}${selectedId === e.id ? ' sel' : ''}`} style={{ left: pct(e.start_ms), width: `max(10px, calc(${pct(e.end_ms)} - ${pct(e.start_ms)}))`, top: i * 30 }}
            aria-pressed={selectedId === e.id} aria-label={`${TYPE_LABEL[e.type]}, ${e.class_name}, ${fmt(e.start_ms)} to ${fmt(e.end_ms)}, ${e.review_status}`} onClick={() => onSelect(e)}>
            <span>{TYPE_LABEL[e.type]}</span>
          </button>)))}
      </div>
      <div className="tl-scale"><span>0:00</span><span>{fmt(durationMs / 2)}</span><span>{fmt(durationMs)}</span></div>
    </div>
  )
}
