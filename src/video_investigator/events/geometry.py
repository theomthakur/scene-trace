"""Pure geometry on normalized coordinates: point-in-polygon with boundary inclusion, polygon validity, polygon/box overlap."""
from __future__ import annotations
from typing import Sequence

Point = tuple[float, float]
EPS = 1e-12


def _cross(o: Point, a: Point, b: Point) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(p: Point, a: Point, b: Point) -> bool:
    if abs(_cross(a, b, p)) > 1e-9:
        return False
    return min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9 and min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    """Ray casting. Points on the boundary count as inside."""
    n = len(poly)
    for i in range(n):
        if _on_segment(p, poly[i], poly[(i + 1) % n]):
            return True
    inside = False
    x, y = p
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xin > x:
                inside = not inside
    return inside


def polygon_area(poly: Sequence[Point]) -> float:
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
        return True
    return any([_on_segment(a, c, d), _on_segment(b, c, d), _on_segment(c, a, b), _on_segment(d, a, b)])


def validate_polygon(poly: Sequence[Point]) -> str | None:
    """Return an error string for degenerate or self-intersecting polygons, else None."""
    if len(poly) < 3:
        return "A zone needs at least 3 points."
    for x, y in poly:
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return "Zone points must be normalized to [0, 1]."
    n = len(poly)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue                       # adjacent edges share a vertex
            if _segments_intersect(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                return "The zone polygon crosses itself."
    if polygon_area(poly) < 1e-6:                  # after the crossing test: a bow tie has zero signed area
        return "The zone has no area (collinear or repeated points)."
    return None


def _clip(subject: list[Point], inside, intersect) -> list[Point]:
    out: list[Point] = []
    for i in range(len(subject)):
        cur, prev = subject[i], subject[i - 1]
        if inside(cur):
            if not inside(prev):
                out.append(intersect(prev, cur))
            out.append(cur)
        elif inside(prev):
            out.append(intersect(prev, cur))
    return out


def polygon_box_intersection_area(poly: Sequence[Point], box: tuple[float, float, float, float]) -> float:
    """Area of polygon ∩ axis-aligned box using Sutherland-Hodgman clipping against the four box edges."""
    x1, y1, x2, y2 = box
    pts = list(poly)

    def lerp_x(xc):
        return lambda a, b: (xc, a[1] + (b[1] - a[1]) * (xc - a[0]) / (b[0] - a[0]))

    def lerp_y(yc):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (yc - a[1]) / (b[1] - a[1]), yc)

    for inside, inter in ((lambda p: p[0] >= x1 - EPS, lerp_x(x1)), (lambda p: p[0] <= x2 + EPS, lerp_x(x2)),
                          (lambda p: p[1] >= y1 - EPS, lerp_y(y1)), (lambda p: p[1] <= y2 + EPS, lerp_y(y2))):
        if not pts:
            return 0.0
        pts = _clip(pts, inside, inter)
    return polygon_area(pts) if len(pts) >= 3 else 0.0


def box_area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def bottom_center(box: tuple[float, float, float, float]) -> Point:
    return ((box[0] + box[2]) / 2.0, box[3])
