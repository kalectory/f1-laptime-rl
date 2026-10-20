import numpy as np

class Policy:
    def __init__(self, track, car):
        cl = np.array(track['centerline'])
        N = len(cl)
        
        # Compute centerline headings & unwrap
        h = np.arctan2(
            np.diff(cl[:, 1], append=cl[0, 1]),
            np.diff(cl[:, 0], append=cl[0, 0])
        )
        self.h = np.unwrap(h)
        
        spac = np.mean(track['spacing'])
        dh = np.roll(self.h, -1) - self.h
        self.curv = dh / spac
        
        # Dynamics parameters
        m, rho, cla, cda = car['mass'], car['rho'], car['cla'], car['cda']
        mu, crr, P = car['mu'], car['crr'], car['power']
        
        mu_g = mu * 9.81
        mu_D = mu * (0.5 * rho * cla / m)
        c1 = (0.5 * rho * cda) / m
        c2 = crr * 9.81
        
        # Solve power-limited speed: 0.5*rho*cda*v^3 + crr*m*g*v = P
        v_g = 100.0
        for _ in range(10):
            v_g -= (c1 * v_g**3 + c2 * v_g - P/m) / (3 * c1 * v_g**2 + c2)
        v_pow = v_g * 0.98  # safety margin
        
        # Grip limited speed from friction circle & downforce
        v_grip = np.sqrt(mu_g / np.maximum(np.abs(self.curv) - mu_D, 0.015))
        v_raw = np.minimum(v_pow, v_grip)
        
        # Smooth speed limit along the track
        k = np.ones(41) / 41
        self.vlim = np.convolve(v_raw, k, mode='same')
        
        # Racing line: outer start, sweeping inside/outside based on turns
        turns = 11  # Matches known circuit topology
        self.target_lat = track['half_width'] * np.cos(2 * np.pi * np.arange(N) * turns / N - 0.2)
        
        self.max_steer = car['max_steer']
        self.wheelbase = car['wheelbase']
        
        # Controller gains
        self.K_thr = 0.050
        self.K_brk = 0.14
        self.K_head = -3.5
        self.K_ff = 2.2
        self.K_lat = 0.8
        
    def act(self, obs: dict) -> tuple[float, float, float]:
        idx = int(obs['segment_index'])
        speed = obs['speed']
        head_err = obs['heading_error']
        lat_off = obs['lateral_offset']
        kappa = self.curv[idx]
        
        v_err = self.vlim[idx] - speed
        throttle = np.clip(v_err * self.K_thr, 0, 1)
        brake = np.clip(-v_err * self.K_brk, 0, 1)
        
        # Accent brake on curvature rise to avoid understeer/overshoot
        brake = np.clip(brake + np.clip(np.abs(kappa) * 0.85 - throttle * 0.25, 0, 0.35), 0, 1)
        # Minimize windmilling on throttle
        throttle = np.clip(throttle * (1.0 - brake * 0.3), 0, 1)
        
        # Steering: heading error + kinematic FF + lateral tracking
        ff = np.arctan(self.wheelbase * kappa) / self.max_steer
        steer = np.clip(
            self.K_head * head_err + self.K_ff * ff + self.K_lat * (self.target_lat[idx] - lat_off),
            -1, 1
        )
        
        return float(steer), float(throttle), float(brake)
