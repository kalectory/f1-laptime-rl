import math
import numpy as np


class Policy:
    def __init__(self, track, car):
        C = np.array(track["centerline"], dtype=float)
        Np = len(C)
        self.Np = Np
        self.car = car
        g = 9.81
        m = car["mass"]
        rho = car["rho"]
        self.c = 0.5 * rho * car["cla"] / m
        self.cd = 0.5 * rho * car["cda"] / m
        self.crr = car["crr"]
        self.mu = car["mu"]
        self.L = car["wheelbase"]
        self.ms = car["max_steer"]
        self.m = m
        self.power = car["power"]
        self.fmax = car["max_drive_force"]

        T = np.roll(C, -1, 0) - np.roll(C, 1, 0)
        T /= np.linalg.norm(T, axis=1)[:, None]
        Nn = np.stack([-T[:, 1], T[:, 0]], 1)

        # ---- min-curvature racing line on coarse grid ----
        step = 5
        ci = np.arange(0, Np, step)
        Cc = C[ci]
        Nc = Nn[ci]
        M = len(ci)
        D = np.zeros((M, M))
        for i in range(M):
            D[i, (i - 1) % M] += 1.0
            D[i, i] -= 2.0
            D[i, (i + 1) % M] += 1.0
        Ax = D * Nc[:, 0][None, :]
        Ay = D * Nc[:, 1][None, :]
        bx = D @ Cc[:, 0]
        by = D @ Cc[:, 1]
        H = Ax.T @ Ax + Ay.T @ Ay + 1e-3 * np.eye(M)
        gv = -(Ax.T @ bx + Ay.T @ by)
        wb = 5.1
        W = np.zeros(M)
        tgt = np.zeros(M)
        n = np.zeros(M)
        for _ in range(30):
            n = np.linalg.solve(H + np.diag(W), gv + W * tgt)
            viol = (np.abs(n) > wb + 0.01) & (W == 0)
            if not viol.any():
                break
            W[viol] = 1e4
            tgt[viol] = np.sign(n[viol]) * wb
        n = np.clip(n, -wb, wb)

        nf = np.interp(np.arange(Np), ci, n, period=Np)
        for _ in range(30):
            nf = 0.25 * np.roll(nf, 1) + 0.5 * nf + 0.25 * np.roll(nf, -1)
        nf = np.clip(nf, -5.3, 5.3)
        P = C + nf[:, None] * Nn
        self.P = P

        a = P - np.roll(P, 1, 0)
        b = np.roll(P, -1, 0) - P
        cc = np.roll(P, -1, 0) - np.roll(P, 1, 0)
        cross = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
        k = 2 * cross / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
                         * np.linalg.norm(cc, axis=1) + 1e-9)
        for _ in range(3):
            k = (np.roll(k, 2) + np.roll(k, 1) + k + np.roll(k, -1) + np.roll(k, -2)) / 5.0
        self.k = k
        self.th = np.arctan2(cc[:, 1], cc[:, 0])
        self.Nr = np.stack([-np.sin(self.th), np.cos(self.th)], 1)
        ds = np.linalg.norm(b, axis=1)
        self.ds = ds

        kk = np.abs(k)
        kk = np.max(np.stack([np.roll(kk, s) for s in range(-3, 4)]), axis=0)
        self.kk = kk
        mul = self.mu * 0.92
        self.mul = mul
        c = self.c
        vmax = np.full(Np, 110.0)
        mask = kk > mul * c + 1e-9
        vmax[mask] = np.minimum(110.0, np.sqrt(mul * g / (kk[mask] - mul * c)))
        v = vmax.copy()
        for idx in range(2 * Np - 1, -1, -1):
            i = idx % Np
            vn = v[(i + 1) % Np]
            v2 = vn * vn
            ag = mul * (g + c * v2)
            al = v2 * kk[i]
            alng = math.sqrt(max(ag * ag - al * al, 0.0))
            drag = self.cd * v2 + self.crr * (g + c * v2)
            vi = math.sqrt(v2 + 2 * ds[i] * (alng + drag))
            if vi < v[i]:
                v[i] = vi
        self.vb = v
        self.aplan = (np.roll(v, -1) ** 2 - v ** 2) / (2 * ds)

    def act(self, obs):
        g = 9.81
        Np = self.Np
        v = float(obs["speed"])
        x = float(obs["x"])
        y = float(obs["y"])
        h = float(obs["heading"])
        yr = float(obs["yaw_rate"])
        seg = int(obs["segment_index"])

        dtp = 0.06
        hp = h + yr * dtp
        xp = x + v * math.cos(h + 0.5 * yr * dtp) * dtp
        yp = y + v * math.sin(h + 0.5 * yr * dtp) * dtp

        cand = (seg + np.arange(-20, 45)) % Np
        d = (self.P[cand, 0] - xp) ** 2 + (self.P[cand, 1] - yp) ** 2
        j = int(cand[int(np.argmin(d))])

        e = (self.P[j, 0] - xp) * self.Nr[j, 0] + (self.P[j, 1] - yp) * self.Nr[j, 1]
        psi = (self.th[j] - hp + math.pi) % (2 * math.pi) - math.pi
        lead = int(v * 0.05 / 2.0)
        kff = float(self.k[(j + lead) % Np])
        Ld = 5.0 + 0.3 * v
        kc = kff + 2.0 * e / (Ld * Ld) + 2.0 * psi / Ld
        steer = math.atan(self.L * kc) / self.ms
        steer = max(-1.0, min(1.0, steer))

        # speed control
        js = (j + int(round(v * 0.1 / 2.0)) + 1) % Np
        vt = float(self.vb[js])
        ap = float(self.aplan[js])
        c = self.c
        Nm = g + c * v * v
        agrip = self.mu * Nm
        alat = v * v * abs(kff)
        aavail = math.sqrt(max((0.95 * agrip) ** 2 - alat ** 2, 0.0))
        fd = min(self.power / max(v, 1.0), self.fmax) / self.m
        cap = min(1.0, aavail / fd) if fd > 0 else 1.0
        if v < 3.0:
            cap = 1.0
        drag = self.cd * v * v + self.crr * Nm
        throttle = 0.0
        brake = 0.0
        if v < vt - 0.5:
            throttle = cap
        else:
            ades = ap + 2.0 * (vt - v)
            along = ades + drag
            if along >= 0:
                throttle = min(cap, along / fd)
            else:
                brake = min(1.0, -along / agrip)
        return (steer, max(0.0, throttle), max(0.0, brake))
