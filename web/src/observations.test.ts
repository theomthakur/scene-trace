import { describe, expect, it } from 'vitest'
import { boxesAt, groupByTime, type Obs } from './observations'

const o = (t: number, id: number, state = 'confirmed'): Obs => ({ t_ms: t, track_id: id, class_name: 'person', confidence: 0.9, box: [0, 0, 1, 1], track_state: state, source: 'detector' })
const idx = groupByTime([o(0, 1), o(200, 1), o(200, 2), o(400, 1, 'tentative'), o(1000, 1)])

describe('boxesAt', () => {
  it('paints the latest sample within tolerance', () => { expect(boxesAt(idx, 250, 250).map(b => b.track_id).sort()).toEqual([1, 2]) })
  it('paints nothing when the player is further than tolerance past the last sample (no stale boxes)', () => { expect(boxesAt(idx, 700, 250)).toEqual([]) })
  it('paints nothing before the first sample', () => { expect(boxesAt(idx, -5, 250)).toEqual([]) })
  it('hides tentative tracks', () => { expect(boxesAt(idx, 420, 250)).toEqual([]) })
  it('uses an exact sample time', () => { expect(boxesAt(idx, 1000, 0)).toHaveLength(1) })
  it('handles an empty index', () => { expect(boxesAt(groupByTime([]), 100, 250)).toEqual([]) })
})
