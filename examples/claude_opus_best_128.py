import math
import numpy as np


class Policy:
    def __init__(self, track, car):
        self.car = car
        C = np.array(track['centerline'], dtype=float)
        n = len(C)
        self.n = n
        hw = track['half_width']
        wmax = hw - 1.0

        def normals(P):
            t = np.roll(P, -1, 0) - np.roll(P, 1, 0)
            t /= np.linalg.norm(t, axis=1)[:, None]
            return np.stack([-t[:, 1], t[:, 0]], 1)

        # ---- min-curvature racing line at half resolution ----
        Ch = C[::2]
        M = len(Ch)
        nh = normals(Ch)
        I = np.eye(M)
        D = -2.0 * I + np.roll(I, 1, 1) + np.roll(I, -1, 1)
        Ax = D * nh[:, 0][None, :]
        Ay = D * nh[:, 1][None, :]
        H = Ax.T @ Ax + Ay.T @ Ay + 1e-4 * I
        g = -(Ax.T @ (D @ Ch[:, 0]) + Ay.T @ (D @ Ch[:, 1]))
        fixed = np.zeros(M, bool)
        val = np.zeros(M)
        w = np.zeros(M)
        for it in range(60):
            f = ~fixed
            w = val.copy()
            rhs = g[f] - H[np.ix_(f, fixed)] @ val[fixed]
            try:
                w[f] = np.linalg.solve(H[np.ix_(f, f)], rhs)
            except Exception:
                break
            viol = f & (np.abs(w) > wmax)
            if viol.any():
                fixed[viol] = True
                val[viol] = np.sign(w[viol]) * wmax
                continue
            grad = H @ w - g
            rel = fixed & (grad * np.sign(val) > 0)
            if not rel.any():
                break
            fixed[rel] = False
            val[rel] = 0.0
        w = np.clip(w, -wmax, wmax)

        # upsample to full resolution
        j = np.arange(n)
        u = j / 2.0
        lo = np.floor(u).astype(int) % M
        fr = u - np.floor(u)
        wf = w[lo] * (1 - fr) + w[(lo + 1) % M] * fr
        nf = normals(C)
        P = C + nf * wf[:, None]
        self.P = P

        # ---- curvature ----
        a = np.roll(P, 3, 0)
        b = P
        c = np.roll(P, -3, 0)
        ab = b - a
        bc = c - b
        ac = c - a
        cr = np.abs(ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0])
        den = (np.linalg.norm(ab, axis=1) * np.linalg.norm(bc, axis=1)
               * np.linalg.norm(ac, axis=1) + 1e-9)
        k = 2.0 * cr / den
        ks = np.zeros(n)
        for s in range(-2, 3):
            ks += np.roll(k, s)
        k = np.maximum(ks / 5.0, k * 0.8)
        self.kappa = k
        ds = np.linalg.norm(np.roll(P, -1, 0) - P, axis=1)
        self.ds = ds

        # ---- speed profile ----
        m = car['mass']
        G = 9.81
        cl = 0.5 * car['rho'] * car['cla'] / m
        cd = 0.5 * car['rho'] * car['cda'] / m
        crr = car['crr']
        mue = car['mu'] * 0.95
        vmax = np.sqrt(mue * G / np.maximum(k - mue * cl, 1e-7))
        vmax = np.minimum(vmax, 120.0)
        vp = vmax.copy()
        for rep in range(2):
            for i in range(n - 1, -1, -1):
                i1 = (i + 1) % n
                v1 = vp[i1]
                ag = mue * (G + cl * v1 * v1)
                al = v1 * v1 * k[i1]
                along = math.sqrt(max(ag * ag - al * al, 0.0)) + cd * v1 * v1 + crr * (G + cl * v1 * v1)
                vv = math.sqrt(v1 * v1 + 2 * along * ds[i])
                if vv < vp[i]:
                    vp[i] = vv
        self.vp = vp
        self.idx = None

    def act(self, obs):
        car = self.car
        n = self.n
        P = self.P
        x = obs['x']; y = obs['y']; h = obs['heading']; v = obs['speed']
        if self.idx is None:
            d2 = (P[:, 0] - x) ** 2 + (P[:, 1] - y) ** 2
            self.idx = int(np.argmin(d2))
        else:
            cand = (self.idx + np.arange(-5, 45)) % n
            d2 = (P[cand, 0] - x) ** 2 + (P[cand, 1] - y) ** 2
            self.idx = int(cand[int(np.argmin(d2))])
        idx = self.idx

        # ---- steering: pure pursuit from predicted pose ----
        L = car['wheelbase']
        tp = 0.05
        hp = h + obs['yaw_rate'] * tp
        xp = x + v * math.cos(h) * tp
        yp = y + v * math.sin(h) * tp
        Ld = 5.0 + 0.12 * v
        jj = (idx + int((Ld + v * tp) / 2.0) + 1) % n
        dx = P[jj, 0] - xp
        dy = P[jj, 1] - yp
        Lr = max(math.hypot(dx, dy), 1.0)
        alpha = math.atan2(dy, dx) - hp
        alpha = (alpha + math.pi) % (2 * math.pi) - math.pi
        delta = math.atan(2.0 * L * math.sin(alpha) / Lr)
        steer = max(-1.0, min(1.0, delta / car['max_steer']))

        # ---- speed control ----
        m = car['mass']
        G = 9.81
        Nf = m * G + 0.5 * car['rho'] * car['cla'] * v * v
        mu = car['mu']
        if obs.get('on_gravel', False):
            mu = car['mu_gravel']
        agrip = mu * Nf / m
        drag = (0.5 * car['rho'] * car['cda'] * v * v + car['crr'] * Nf) / m
        nah = int((4.0 + 0.2 * v) / 2.0) + 2
        offs = np.arange(0, nah)
        segs = (idx + offs) % n
        dist = np.cumsum(self.ds[segs])
        ks = (idx + offs + 1) % n
        vt = self.vp[ks]
        a_des = float(np.min((vt * vt - v * v) / (2.0 * np.maximum(dist, 0.5))))
        kap = max(self.kappa[idx], abs(math.tan(obs['steer_angle'])) / L)
        alat = v * v * kap
        a_av = math.sqrt(max(agrip * agrip - alat * alat, 0.0))
        Fmax = min(car['power'] / max(v, 1.0), car['max_drive_force'])
        throttle = 0.0
        brake = 0.0
        if a_des + drag > 0:
            req = (a_des + drag) * m
            throttle = min(req / Fmax, 1.0, a_av * m / Fmax)
            if a_des > 0.5:
                throttle = min(1.0, a_av * m / Fmax)
            throttle = max(0.0, throttle)
        else:
            Fb = (-a_des - drag) * m
            brake = min(Fb / (mu * Nf), a_av / max(agrip, 1e-6))
            brake = max(0.0, min(1.0, brake))
        return (steer, throttle, brake)
