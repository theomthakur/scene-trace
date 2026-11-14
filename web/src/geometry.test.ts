import { describe, expect, it } from 'vitest'
import { contentRect, insideContent, toNormalized, toPixels } from './geometry'

describe('contentRect (object-fit: contain)', () => {
  it('has no bars when the container matches the video aspect ratio', () => {
    const r = contentRect(800, 450, 1920, 1080); expect([r.x, r.y, r.w, r.h].map(Math.round)).toEqual([0, 0, 800, 450])
  })
  it('letterboxes a wide video in a tall container', () => {
    const r = contentRect(800, 800, 1920, 1080)
    expect(r.w).toBeCloseTo(800); expect(r.h).toBeCloseTo(450); expect(r.x).toBeCloseTo(0); expect(r.y).toBeCloseTo(175)
  })
  it('pillarboxes a portrait video in a wide container', () => {
    const r = contentRect(1000, 500, 540, 960)
    expect(r.h).toBeCloseTo(500); expect(r.w).toBeCloseTo(281.25); expect(r.x).toBeCloseTo(359.375); expect(r.y).toBeCloseTo(0)
  })
  it('is empty for degenerate sizes', () => {
    expect(contentRect(0, 100, 10, 10).w).toBe(0)
    expect(contentRect(100, 100, 0, 10).h).toBe(0)
  })
})

describe('pointer mapping uses the video content, not the outer container', () => {
  const r = contentRect(800, 800, 1920, 1080)          // bars above and below
  it('maps the centre of the container to the centre of the video', () => {
    expect(toNormalized(400, 400, r)[0]).toBeCloseTo(0.5); expect(toNormalized(400, 400, r)[1]).toBeCloseTo(0.5)
  })
  it('maps the top-left of the visible video to (0,0) and not the container corner', () => {
    expect(toNormalized(0, r.y, r).map(Math.abs).every(v => v < 1e-9)).toBe(true)
    expect(toNormalized(0, 0, r)[1]).toBe(0)                     // a click in the top bar clamps to the edge
    expect(toNormalized(0, 0, r, false)[1]).toBeLessThan(0)      // unclamped it is outside the video
  })
  it('round-trips pixels through normalized space', () => {
    for (const [px, py] of [[10, 200], [400, 400], [790, 620]] as const) {
      const [nx, ny] = toNormalized(px, py, r, false); const [bx, by] = toPixels(nx, ny, r)
      expect(bx).toBeCloseTo(px); expect(by).toBeCloseTo(py)
    }
  })
  it('knows when a point is on a letterbox bar', () => {
    expect(insideContent(400, 10, r)).toBe(false); expect(insideContent(400, 400, r)).toBe(true)
  })
})
