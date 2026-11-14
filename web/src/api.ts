// Typed client for the local API. Field names mirror the backend contract (tests/test_contract_types.py checks they match real responses).
import type { Obs } from './observations'

/** Build-time API base for a separately hosted backend (for example https://api.example.com). Empty means same origin. */
export const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/$/, '')

export interface ZoneT { id: string; name: string; role: 'restricted' | 'passage'; polygon: [number, number][] }
export interface VideoT {
  id: string; display_name: string; source_sha256: string; size_bytes: number; duration_ms: number; width: number; height: number; codec: string | null; fps: number | null
  rotation: number | null; timestamps_ok: boolean | null; ready: boolean; derivative_status: string; derivative_error: string | null; media_url: string | null; created_at: string; zone_version?: number | null
}
export interface RunError { code: string; message: string; retryable: boolean }
export interface RunT {
  id: string; video_id: string; zone_version: number; state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'; attempt: number; progress: number; processed_ms: number
  errors: RunError[]; quality_flags: string[]; cancel_requested: boolean; complete: boolean; config_hash: string; pipeline_version: string | null; detector: Record<string, unknown> | null
  timings: Record<string, number> | null; manifest_sha256: string | null; zones: ZoneT[]; created_at: string; finished_at: string | null; data_source: string; retry_count: number
}
export interface FrameRef { role: string; t_ms: number; frame_t_ms?: number; overlay?: string; original?: string; missing?: boolean }
export interface EventT {
  id: string; event_key: string; evidence_base: string; run_id: string; type: 'zone_entry' | 'stationary_object' | 'passage_occupancy'; zone_id: string | null; start_ms: number; end_ms: number
  track_ids: number[]; class_name: string; rule_version: string; details: Record<string, unknown>; uncertainty_flags: string[]
  evidence: { frames: FrameRef[]; clip: string | null; clip_range_ms: [number, number]; clip_error?: string }
  description: string; group_id: string; source: 'detector' | 'fixture'; review_status: 'unreviewed' | 'confirmed' | 'dismissed' | 'uncertain'; review_note: string; review_version: number; reviewed_at: string | null
}
export interface SearchResult { results: EventT[]; interpreted: { event_types: string[]; classes: string[]; zone_ids: string[]; review_status: string[]; understood: string[]; ignored_terms: string[]; after_ms: number | null; before_ms: number | null }; unsupported: boolean; notices: string[]; limit: number; ordering?: string }

/** Prefix backend-relative media URLs with the API base (a no-op for same-origin hosting and for static demo URLs). */
export const mediaSrc = (url: string | null): string | null => (url && url.startsWith('/api/') ? `${API_BASE}${url}` : url)

export interface SemanticInfo { similarity: number; rank: number; model: string; index_built_at: string; best_item: { kind: 'frame' | 'crop'; role: string; t_ms: number; box: number[] | null; track_id: number | null; frame_url: string } }
export type SemanticHit = EventT & { semantic: SemanticInfo }
export interface SemanticResult { results: SemanticHit[]; unsupported: boolean; notices: string[]; score_meaning: string; ordering: string; structured_constraints_applied: { classes: string[]; event_types: string[]; zone_ids: string[] }; candidates_after_structured_filter?: number; model?: { name: string }; source?: string }
export interface ExplanationT {
  id: string; event_id: string; status: 'ok' | 'flagged'; text: string; model: { name: string; revision: string; source: string }; created_at: string
  frames: { role: string; t_ms: number; kind: string; frame_url: string }[]; prompt_sha256: string; flags: string[]; disclaimer: string
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body?: Record<string, unknown>) { super(message) }
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let b: { error?: { code?: string; message?: string } & Record<string, unknown> } = {}
    try { b = await r.json() } catch { /* not json */ }
    throw new ApiError(r.status, b.error?.code ?? 'error', b.error?.message ?? r.statusText, b.error)
  }
  return r.json() as Promise<T>
}
const jsonInit = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export interface Backend {
  mode: 'live' | 'demo'
  listVideos(): Promise<VideoT[]>
  getVideo(id: string): Promise<VideoT>
  upload(file: File, name: string, onProgress: (f: number) => void): Promise<VideoT>
  getZones(id: string): Promise<{ version: number | null; zones: ZoneT[] }>
  putZones(id: string, zones: ZoneT[]): Promise<{ version: number; zones: ZoneT[] }>
  listRuns(videoId: string): Promise<RunT[]>
  createRun(videoId: string, zoneVersion: number | null, requestId: string): Promise<RunT>
  getRun(id: string): Promise<RunT>
  cancelRun(id: string): Promise<void>
  restartRun(id: string): Promise<void>
  observations(runId: string): Promise<Obs[]>
  events(runId: string): Promise<{ events: EventT[]; complete: boolean; quality_flags: string[]; note: string | null }>
  search(runId: string, query: string, filters: Record<string, unknown>): Promise<SearchResult>
  semanticSearch(runId: string, query: string, filters: Record<string, unknown>): Promise<SemanticResult>
  explain(eventId: string, frames: string[]): Promise<ExplanationT>
  explanations(eventId: string): Promise<ExplanationT[]>
  review(eventId: string, verdict: string, note: string, expected: number): Promise<EventT>
  evidenceUrl(ev: EventT, name: string): string
  reportUrl(runId: string, format: 'json' | 'markdown' | 'html'): string
  evaluations(): Promise<string[]>
  evaluation(id: string): Promise<Record<string, any>>
}

export const liveBackend: Backend = {
  mode: 'live',
  listVideos: async () => (await j<{ videos: VideoT[] }>(await fetch(API_BASE + '/api/videos'))).videos,
  getVideo: async id => j(await fetch(`${API_BASE}/api/videos/${id}`)),
  upload: (file, name, onProgress) => new Promise((resolve, reject) => {
    const fd = new FormData(); fd.append('file', file); fd.append('display_name', name)
    const x = new XMLHttpRequest(); x.open('POST', `${API_BASE}/api/videos`)
    x.upload.onprogress = e => { if (e.lengthComputable) onProgress(e.loaded / e.total) }
    x.onload = () => {
      let b: any = {}; try { b = JSON.parse(x.responseText) } catch { /* ignore */ }
      if (x.status >= 200 && x.status < 300) resolve(b as VideoT); else reject(new ApiError(x.status, b.error?.code ?? 'error', b.error?.message ?? x.statusText, b.error))
    }
    x.onerror = () => reject(new ApiError(0, 'network', 'Could not reach the backend. Is it running on port 8000?'))
    x.send(fd)
  }),
  getZones: async id => j(await fetch(`${API_BASE}/api/videos/${id}/zones`)),
  putZones: async (id, zones) => j(await fetch(`${API_BASE}/api/videos/${id}/zones`, jsonInit('PUT', { zones }))),
  listRuns: async videoId => (await j<{ runs: RunT[] }>(await fetch(`${API_BASE}/api/runs?video_id=${videoId}`))).runs,
  createRun: async (video_id, zone_version, client_request_id) => j(await fetch(API_BASE + '/api/runs', jsonInit('POST', { video_id, zone_version, client_request_id }))),
  getRun: async id => j(await fetch(`${API_BASE}/api/runs/${id}`)),
  cancelRun: async id => { await j(await fetch(`${API_BASE}/api/runs/${id}/cancel`, { method: 'POST' })) },
  restartRun: async id => { await j(await fetch(`${API_BASE}/api/runs/${id}/restart`, { method: 'POST' })) },
  observations: async runId => {
    const out: Obs[] = []; let cursor: number | null = null
    do {
      const r: { observations: Obs[]; next_cursor: number | null } = await j(await fetch(`${API_BASE}/api/runs/${runId}/observations?limit=5000${cursor ? `&cursor=${cursor}` : ''}`))
      out.push(...r.observations); cursor = r.next_cursor
    } while (cursor)
    return out
  },
  events: async runId => j(await fetch(`${API_BASE}/api/runs/${runId}/events?limit=500`)),
  search: async (runId, query, filters) => j(await fetch(`${API_BASE}/api/runs/${runId}/search`, jsonInit('POST', { query, filters }))),
  semanticSearch: async (runId, query, filters) => j(await fetch(`${API_BASE}/api/runs/${runId}/search/semantic`, jsonInit('POST', { query, filters }))),
  explain: async (id, frames) => j(await fetch(`${API_BASE}/api/events/${id}/explain`, jsonInit('POST', { frames }))),
  explanations: async id => (await j<{ explanations: ExplanationT[] }>(await fetch(`${API_BASE}/api/events/${id}/explanations`))).explanations,
  review: async (id, verdict, note, expected_version) => j(await fetch(`${API_BASE}/api/events/${id}/review`, jsonInit('PUT', { verdict, note, expected_version }))),
  evidenceUrl: (ev, name) => `${API_BASE}${ev.evidence_base}${name}`,
  reportUrl: (runId, format) => `${API_BASE}/api/runs/${runId}/report?format=${format}`,
  evaluations: async () => (await j<{ evaluations: string[] }>(await fetch(API_BASE + '/api/evaluations'))).evaluations,
  evaluation: async id => j(await fetch(`${API_BASE}/api/evaluations/${id}`)),
}
