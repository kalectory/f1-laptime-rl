import math
import bisect

class Policy:
    def __init__(self, track, car):
        self.centerline = track['centerline']
        self.length = track['length']
        self.n = len(self.centerline)
        # Precompute cumulative arc lengths for fast lookahead lookup
        self.cum_dists = [0.0]
        for i in range(1, self.n):
            p0, p1 = self.centerline[i-1], self.centerline[i]
            self.cum_dists.append(self.cum_dists[-1] + math.hypot(p1[0]-p0[0], p1[1]-p0[1]))

    def _wrap(self, angle):
        """Wrap angle to [-pi, pi)."""
        return (angle + math.pi) % (2 * math.pi) - math.pi

    def _find_idx(self, s_val):
        """Find index in centerline corresponding to arc length s_val."""
        idx = bisect.bisect_left(self.cum_dists, s_val)
        if idx >= self.n:
            idx = self.n - 1
        return idx

    def act(self, obs):
        x, y, heading, speed = obs['x'], obs['y'], obs['heading'], obs['speed']
        s = obs['s']

        # --- Steering / Targeting ---
        # Lookahead distance grows with speed to give the controller more horizon
        look_dist = 0.4 * speed + 10.0
        look_dist = max(8.0, min(45.0, look_dist))
        
        target_s = (s + look_dist) % self.length
        idx = self._find_idx(target_s)
        tx, ty = self.centerline[idx]

        dx, dy = tx - x, ty - y
        angle_t = math.atan2(dy, dx)
        diff = self._wrap(angle_t - heading)

        # Racing line offset: push target to the OUTSIDE of the turn.
        # Outside is opposite to turn direction. diff > 0 => turn left => outside is right (-)
        offset = -3.0 * diff
        track_h = obs['track_heading']
        # Rotate perpendicular vector (+90 deg is left normal)
        tx += math.cos(track_h + math.pi / 2) * offset
        ty += math.sin(track_h + math.pi / 2) * offset

        # Recompute heading error relative to offset target
        dx2, dy2 = tx - x, ty - y
        angle_t2 = math.atan2(dy2, dx2)
        diff2 = self._wrap(angle_t2 - heading)

        # Proportional steering with gain slightly reduced at high speed for stability
        steer = 2.8 * diff2
        steer = max(-1.0, min(1.0, steer))

        # --- Throttle & Brake ---
        # Look further ahead to anticipate turns and apply braking early
        brake_look = 0.5 * speed + 15.0
        brake_s = (s + brake_look) % self.length
        idx_b = self._find_idx(brake_s)
        bx, by = self.centerline[idx_b]
        angle_b = math.atan2(by - y, bx - x)
        diff_b = self._wrap(angle_b - heading)

        throttle = 1.0
        brake = 0.0
        # Apply brake if upcoming path curves significantly
        if abs(diff_b) > 0.2:
            brake = min(1.0, (abs(diff_b) - 0.2) * 3.5)
            throttle = max(0.0, 1.0 - brake * 0.7)

        return steer, throttle, brake
