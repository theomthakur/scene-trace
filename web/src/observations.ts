// Frame lookup for overlays. Observations are sampled (for example 5 per second) while the player runs at its own frame rate.
export interface Obs { t_ms: number; track_id: number; class_name: string; confidence: number; box: [number, number, number, number]; track_state: string; source: string }

/** Index observations by sample time. */
export function groupByTime(obs: Obs[]): { times: number[]; byTime: Map<number, Obs[]> } {
  const byTime = new Map<number, Obs[]>()
  for (const o of obs) { const a = byTime.get(o.t_ms); if (a) a.push(o); else byTime.set(o.t_ms, [o]) }
  return { times: [...byTime.keys()].sort((a, b) => a - b), byTime }
}

/**
 * Observations to paint at player time tMs. Returns [] when the nearest sample at or before tMs is older than toleranceMs, so a box is
 * never painted on a frame it does not belong to (after a seek, a long gap, or past the last sample).
 */
export function boxesAt(idx: { times: number[]; byTime: Map<number, Obs[]> }, tMs: number, toleranceMs: number): Obs[] {
  const { times, byTime } = idx
  let lo = 0, hi = times.length - 1, best = -1
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (times[mid] <= tMs) { best = mid; lo = mid + 1 } else hi = mid - 1 }
  if (best < 0 || tMs - times[best] > toleranceMs) return []
  return (byTime.get(times[best]) ?? []).filter(o => o.track_state === 'confirmed')
}
