import math

class Policy:
    def __init__(self, track, car):
        self.cl = track['centerline']
        self.n = len(self.cl)
        self.sp = track.get('spacing', 2.0)

    def _wrap(self, a):
        while a > math.pi: a -= 2 * math.pi
        while a <= -math.pi: a += 2 * math.pi
        return a

    def act(self, obs):
        idx = obs['segment_index']
        v = obs['speed']
        x, y = obs['x'], obs['y']
        h = obs['heading']

        # Dynamic lookahead: ~15m at low speed, up to 50m at high speed
        ahead = min(50.0, 15.0 + v * 0.4)
        i_look = (idx + int(ahead / self.sp)) % self.n
        tx, ty = self.cl[i_look]

        dx, dy = tx - x, ty - y
        # Fallback if target is too close (e.g. start/finish wrap or very low speed)
        if math.hypot(dx, dy) < 1.0:
            i_look = (i_look + 40) % self.n
            tx, ty = self.cl[i_look]
            dx, dy = tx - x, ty - y

        # Desired heading towards lookahead point
        err = self._wrap(math.atan2(dy, dx) - h)
        
        # Steering command proportional to error, clamped to [-1, 1]
        ste = max(-1.0, min(1.0, err * 2.3))

        # Brake increases with turn sharpness to stay within friction circle
        brk = min(0.9, max(0.0, (abs(err) - 0.15) * 1.6))
        # Avoid simultaneous throttle and brake
        thr = 1.0 if brk < 0.05 else 0.0

        return float(ste), float(thr), float(brk)
