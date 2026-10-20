"""The single fixed circuit: a closed centerline resampled every SPACING meters.

Pure Python so the simulator has no third-party dependencies. The geometry is
deterministic; every rollout races the identical track from the identical grid slot.
"""

from __future__ import annotations

import math
from functools import lru_cache

NAME = "Trajectory Grand Prix Circuit"
HALF_WIDTH = 6.0  # asphalt: |lateral offset| <= 6 m
GRAVEL_WIDTH = 5.0  # run-off beyond the asphalt edge; wall at 11 m from centerline
SPACING = 2.0  # centerline sample spacing (m)

# Control points (m), driven in this order (clockwise overall, y up). Start/finish is
# the first point, car facing +x down the main straight.
CONTROL_POINTS: list[tuple[float, float]] = [
    (0, 0),
    (350, 0),
    (700, 0),
    (1000, 0),
    # T1: heavy-braking right hairpin
    (1075, -15),
    (1100, -75),
    (1070, -135),
    (1000, -150),
    # T2-T5: esses
    (900, -145),
    (820, -185),
    (740, -150),
    (660, -190),
    (580, -170),
    # T6-T7: long left-hander onto the back straight
    (490, -200),
    (430, -280),
    (440, -380),
    (520, -440),
    (700, -455),
    (950, -455),
    (1150, -450),
    # T8-T9: chicane
    (1200, -425),
    (1240, -460),
    (1290, -440),
    # T10: fast sweeping left, uphill run north
    (1370, -380),
    (1410, -270),
    (1405, -100),
    (1390, 60),
    # T11: left onto the top straight
    (1340, 170),
    (1230, 220),
    (900, 230),
    (550, 225),
    (250, 215),
    # T12-T13: tight lefts back onto the main straight
    (40, 200),
    (-90, 170),
    (-140, 90),
    (-110, 20),
    (-50, 0),
]


def _catmull_rom_closed(points, samples_per_segment=60):
    """Centripetal Catmull-Rom through closed control points (no overshoot/cusps)."""
    n = len(points)
    out = []
    for i in range(n):
        p0, p1, p2, p3 = (points[(i + k - 1) % n] for k in range(4))

        def tj(ti, pa, pb):
            return ti + math.hypot(pb[0] - pa[0], pb[1] - pa[1]) ** 0.5

        t0 = 0.0
        t1 = tj(t0, p0, p1)
        t2 = tj(t1, p1, p2)
        t3 = tj(t2, p2, p3)
        for k in range(samples_per_segment):
            t = t1 + (t2 - t1) * k / samples_per_segment

            def lerp(pa, pb, ta, tb):
                if tb == ta:
                    return pa
                wa, wb = (tb - t) / (tb - ta), (t - ta) / (tb - ta)
                return (wa * pa[0] + wb * pb[0], wa * pa[1] + wb * pb[1])

            a1 = lerp(p0, p1, t0, t1)
            a2 = lerp(p1, p2, t1, t2)
            a3 = lerp(p2, p3, t2, t3)
            b1 = lerp(a1, a2, t0, t2)
            b2 = lerp(a2, a3, t1, t3)
            out.append(lerp(b1, b2, t1, t2))
    return out


def _resample_closed(dense, spacing):
    pts = dense + [dense[0]]
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1]
    n = max(8, round(total / spacing))
    step = total / n
    out, j = [], 0
    for i in range(n):
        s = i * step
        while cum[j + 1] < s:
            j += 1
        seg = cum[j + 1] - cum[j]
        u = 0.0 if seg == 0 else (s - cum[j]) / seg
        a, b = pts[j], pts[j + 1]
        out.append((a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])))
    return out, total


class Track:
    def __init__(self):
        dense = _catmull_rom_closed(CONTROL_POINTS)
        pts, _ = _resample_closed(dense, SPACING)
        self.points = pts
        self.n = len(pts)
        # exact polyline length of the resampled loop
        self.seg_len = []
        for i in range(self.n):
            a, b = pts[i], pts[(i + 1) % self.n]
            self.seg_len.append(math.hypot(b[0] - a[0], b[1] - a[1]))
        self.cum_s = [0.0]
        for L in self.seg_len[:-1]:
            self.cum_s.append(self.cum_s[-1] + L)
        self.length = self.cum_s[-1] + self.seg_len[-1]
        self.half_width = HALF_WIDTH
        self.wall = HALF_WIDTH + GRAVEL_WIDTH
        self.heading = []
        for i in range(self.n):
            a, b = pts[i], pts[(i + 1) % self.n]
            self.heading.append(math.atan2(b[1] - a[1], b[0] - a[0]))

    def project(self, x, y, hint):
        """Nearest point on the centerline near segment `hint`.

        Returns (segment_index, s, lateral_offset). Lateral offset is positive to the
        left of the driving direction. Search is local (+-40 segments) so a car can
        never "teleport" to another part of the circuit.
        """
        best = None
        for k in range(hint - 40, hint + 41):
            i = k % self.n
            ax, ay = self.points[i]
            bx, by = self.points[(i + 1) % self.n]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            u = ((x - ax) * dx + (y - ay) * dy) / L2 if L2 else 0.0
            u = 0.0 if u < 0 else 1.0 if u > 1 else u
            px, py = ax + u * dx, ay + u * dy
            d2 = (x - px) ** 2 + (y - py) ** 2
            if best is None or d2 < best[0]:
                L = math.sqrt(L2) or 1.0
                cross = (dx * (y - ay) - dy * (x - ax)) / L
                best = (d2, i, self.cum_s[i] + u * self.seg_len[i], cross)
        _, i, s, d = best
        return i, s, d

    def to_dict(self):
        return {
            "name": NAME,
            "centerline": [[round(x, 3), round(y, 3)] for x, y in self.points],
            "spacing": self.length / self.n,
            "length": self.length,
            "half_width": HALF_WIDTH,
            "gravel_width": GRAVEL_WIDTH,
            "wall_offset": self.wall,
            "start": {"x": self.points[0][0], "y": self.points[0][1], "heading": self.heading[0]},
        }


@lru_cache(maxsize=1)
def get_track() -> Track:
    return Track()
