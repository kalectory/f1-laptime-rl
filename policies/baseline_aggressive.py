"""Reference policy: follow the centerline with pure pursuit and a grip-limited speed profile.

Deliberately simple (no racing line) so it is a floor that model-written code should beat.
"""

import math


class Policy:
    def __init__(self, track, car):
        self.pts = track["centerline"]
        self.n = len(self.pts)
        self.ds = track["spacing"]
        self.car = car
        n, P = self.n, self.pts
        # curvature from three-point circle fits, smoothed
        k = []
        for i in range(n):
            ax, ay = P[i - 3]
            bx, by = P[i]
            cx, cy = P[(i + 3) % n]
            cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            a = math.dist((ax, ay), (bx, by))
            b = math.dist((bx, by), (cx, cy))
            c = math.dist((ax, ay), (cx, cy))
            k.append(abs(2 * cross / (a * b * c)) if a * b * c else 0.0)
        g, m, mu, rho = 9.81, car["mass"], car["mu"], car["rho"]
        aero = mu * rho * car["cla"] / (2 * m)
        margin = 0.97
        vmax = []
        for ki in k:
            denom = ki - aero * margin
            vmax.append(math.sqrt(mu * margin * g / denom) if denom > 1e-6 else 100.0)
        vmax = [min(v, 100.0) for v in vmax]
        # backward pass: braking-limited approach speeds
        for _ in range(2):
            for i in range(n - 1, -1, -1):
                j = (i + 1) % n
                v = vmax[j]
                a_brake = margin * mu * (g + rho * car["cla"] * v * v / (2 * m))
                vmax[i] = min(vmax[i], math.sqrt(v * v + 2 * a_brake * self.ds))
        self.vref = vmax

    def act(self, obs):
        i = obs["segment_index"]
        v = obs["speed"]
        look = max(8.0, 0.25 * v + 5.0)
        tx, ty = self.pts[(i + int(look / self.ds)) % self.n]
        dx, dy = tx - obs["x"], ty - obs["y"]
        alpha = math.atan2(dy, dx) - obs["heading"]
        alpha = (alpha + math.pi) % (2 * math.pi) - math.pi
        Ld = math.hypot(dx, dy)
        delta = math.atan2(2 * self.car["wheelbase"] * math.sin(alpha), Ld)
        steer = max(-1.0, min(1.0, delta / self.car["max_steer"]))
        target = self.vref[(i + 2) % self.n]
        if v < target - 0.5:
            return steer, 1.0, 0.0
        if v > target + 0.5:
            return steer, 0.0, min(1.0, (v - target) / 4.0)
        return steer, 0.3, 0.0
