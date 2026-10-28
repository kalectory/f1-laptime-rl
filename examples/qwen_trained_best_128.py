import math

class Policy:
    def __init__(self, track, car):
        self.centerline = track['centerline']
        self.N = len(self.centerline)

    def act(self, obs):
        idx = obs['segment_index']
        x, y, h = obs['x'], obs['y'], obs['heading']
        v = obs['speed']

        L = 25.0 + 0.25 * v

        target = None
        for i in range(1, 200):
            ni = (idx + i) % self.N
            pt = self.centerline[ni]
            dx, dy = pt[0]-x, pt[1]-y
            dist = math.hypot(dx, dy)

            if dist > L * 3.0:
                break

            ang = math.atan2(dy, dx) - h
            ang = (ang + math.pi) % (2*math.pi) - math.pi

            if abs(ang) > 1.2:
                continue

            if dist > L:
                target = pt
                break

        if target is None:
            ni = (idx + 1) % self.N
            target = self.centerline[ni]

        tvx, tvy = target[0]-x, target[1]-y
        target_ang = math.atan2(tvy, tvx) - h
        target_ang = (target_ang + math.pi) % (2*math.pi) - math.pi

        steer = target_ang * 1.4
        if steer > 1.0: steer = 1.0
        elif steer < -1.0: steer = -1.0

        brake = abs(target_ang) * 1.4 - 0.10
        if brake < 0.0: brake = 0.0
        elif brake > 0.80: brake = 0.80

        return float(steer), 1.0, float(brake)
