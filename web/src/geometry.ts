// Coordinate transforms between normalized video space [0,1] and the pixels of an element that shows the video with object-fit: contain.
// Boxes and zones are normalized xyxy in the upright frame, so these functions are the only place pixels and video space meet.
export interface Rect { x: number; y: number; w: number; h: number }

/** The rectangle the video's pixels occupy inside a container of the given size (letterboxed or pillarboxed). */
export function contentRect(containerW: number, containerH: number, videoW: number, videoH: number): Rect {
  if (containerW <= 0 || containerH <= 0 || videoW <= 0 || videoH <= 0) return { x: 0, y: 0, w: 0, h: 0 }
  const scale = Math.min(containerW / videoW, containerH / videoH)
  const w = videoW * scale, h = videoH * scale
  return { x: (containerW - w) / 2, y: (containerH - h) / 2, w, h }
}

export function toNormalized(px: number, py: number, r: Rect, clamp = true): [number, number] {
  if (r.w <= 0 || r.h <= 0) return [0, 0]
  const nx = (px - r.x) / r.w, ny = (py - r.y) / r.h
  return clamp ? [Math.min(1, Math.max(0, nx)), Math.min(1, Math.max(0, ny))] : [nx, ny]
}

export function toPixels(nx: number, ny: number, r: Rect): [number, number] {
  return [r.x + nx * r.w, r.y + ny * r.h]
}

export function insideContent(px: number, py: number, r: Rect): boolean {
  return px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h
}
