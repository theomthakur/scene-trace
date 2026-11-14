// Static demo backend: reads precomputed artifacts exported by `python -m video_investigator.cli export-demo`. It runs no model and changes nothing.
import { ApiError, type Backend, type EventT, type RunT, type VideoT, type ZoneT } from './api'
import type { Obs } from './observations'

interface DemoIndex { name: string; video: VideoT; run: RunT; zones: ZoneT[]; events: EventT[]; observations: Obs[]; evaluations: Record<string, any>; generated_at: string; note: string }
let cache: Promise<DemoIndex> | null = null
const load = () => (cache ??= fetch('/demo/index.json').then(r => { if (!r.ok) throw new ApiError(r.status, 'demo_missing', 'No demo bundle found. Run: python -m video_investigator.cli export-demo'); return r.json() }))
const readOnly = () => { throw new ApiError(0, 'demo_read_only', 'Static demo: precomputed results, read only. Start the backend for live processing and reviews.') }

export const demoBackend: Backend = {
  mode: 'demo',
  listVideos: async () => [(await load()).video],
  getVideo: async () => (await load()).video,
  upload: async () => readOnly(),
  getZones: async () => { const d = await load(); return { version: d.run.zone_version, zones: d.zones } },
  putZones: async () => readOnly(),
  listRuns: async () => [(await load()).run],
  createRun: async () => readOnly(),
  getRun: async () => (await load()).run,
  cancelRun: async () => readOnly(),
  restartRun: async () => readOnly(),
  observations: async () => (await load()).observations,
  events: async () => { const d = await load(); return { events: d.events, complete: true, quality_flags: d.run.quality_flags, note: null } },
  search: async (_r, query) => {
    const d = await load(); const q = query.toLowerCase()
    const hits = d.events.filter((e: EventT) => !q || e.description.toLowerCase().includes(q) || e.type.includes(q.replace(/\s+/g, '_')) || e.class_name.includes(q))
    return { results: hits, interpreted: { event_types: [], classes: [], zone_ids: [], review_status: [], understood: ['plain text match on descriptions (static demo)'], ignored_terms: [], after_ms: null, before_ms: null }, unsupported: false, notices: ['Static demo: simple text match over precomputed event descriptions.'], limit: 50 }
  },
  semanticSearch: async () => { throw new ApiError(0, 'demo_read_only', 'Semantic search needs the live backend and its embedding model. The static demo supports keyword search only.') },
  review: async () => readOnly(),
  evidenceUrl: (ev, name) => `/demo/evidence/${ev.event_key}/${name}`,
  reportUrl: (_r, format) => `/demo/report.${format === 'markdown' ? 'md' : format}`,
  evaluations: async () => Object.keys((await load()).evaluations),
  evaluation: async id => (await load()).evaluations[id],
}
