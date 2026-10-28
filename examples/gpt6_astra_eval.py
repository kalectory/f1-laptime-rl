import math
import numpy as np


class Policy:
    def __init__(self, track: dict, car: dict):
        self.car = car
        self.C = np.asarray(track["centerline"], dtype=float)
        self.n = len(self.C)
        self.length = float(track["length"])
        self.spacing = float(track["spacing"])
        self.half_width = float(track["half_width"])
        self.bound = max(0.5, self.half_width - 0.8)

        self.mass = float(car["mass"])
        self.wheelbase = float(car["wheelbase"])
        self.max_steer = float(car["max_steer"])
        self.steer_rate = float(car["max_steer_rate"])
        self.power_acc = float(car["power"]) / self.mass
        self.drive_acc = float(car["max_drive_force"]) / self.mass
        self.mu = float(car["mu"])
        self.mu_gravel = float(car["mu_gravel"])
        self.scrub = float(car["scrub"])
        self.dt = float(car["physics_dt"])
        self.control_dt = float(car["control_dt"])
        self.steps = int(round(self.control_dt / self.dt))

        self.down = 0.5 * float(car["rho"]) * float(car["cla"]) / self.mass
        self.drag0 = float(car["crr"]) * 9.81
        self.drag2 = (
            0.5 * float(car["rho"]) * float(car["cda"]) / self.mass
            + float(car["crr"]) * self.down
        )
        self.g0 = self.mu * 9.81
        self.g2 = self.mu * self.down
        self.gravel_drag = float(car["gravel_drag"])
        self.plan_grip = 0.965
        self.plan_steer_curvature = math.tan(
            min(0.30, self.max_steer * 0.88)
        ) / self.wheelbase

        tangent = np.roll(self.C, -1, axis=0) - np.roll(self.C, 1, axis=0)
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1), 1e-12)[:, None]
        self.normals = np.column_stack((-tangent[:, 1], tangent[:, 0]))

        # Successive, box-constrained curvature minimization, from coarse
        # to fine. The small length term cuts flat-out corners.
        offset = None
        old_count = None
        sizes = [self.n // 8, self.n // 4, self.n // 2, self.n]
        iterations = [700, 850, 1000, 1050]
        for level, count in enumerate(sizes):
            count = max(32, count)
            c, normals = self._sample_reference(count)
            if offset is None:
                offset = np.zeros(count)
            else:
                u = np.arange(count, dtype=float) * old_count / count
                offset = np.interp(
                    u, np.arange(old_count + 1), np.r_[offset, offset[0]]
                )
            offset = self._smooth_line(
                c, normals, offset, iterations[level], 2 if level == 3 else 3
            )
            old_count = count

        offset = self._time_polish(offset)
        racing_points = self.C + self.normals * offset[:, None]
        self.main = self._make_geometry(racing_points)

        # A separate launch line starts at the actual standing-start position,
        # without changing the optimal line used on the approach to the finish.
        center_s = np.arange(self.n, dtype=float) * self.spacing
        u = np.clip(center_s / 155.0, 0.0, 1.0)
        blend = u * u * u * (10.0 + u * (-15.0 + 6.0 * u))
        launch_points = self.C + self.normals * (offset * blend)[:, None]
        self.launch = self._make_geometry(launch_points)
        self.launch["heading"][0] = 0.0
        self.launch["curvature"][0] = 0.0

        self.profile_ds = self.main["ds"].copy()
        profile_k = self.main["curvature"].copy()
        launch_mask = center_s < 175.0
        self.profile_ds[launch_mask] = self.launch["ds"][launch_mask]
        profile_k[launch_mask] = self.launch["curvature"][launch_mask]
        self.speed2, self.acceleration = self._speed_profile(
            profile_k, self.profile_ds, float(self.main["curvature"][0])
        )

        self.local_indices = np.arange(-12, 13, dtype=int)

    @staticmethod
    def _wrap(angle):
        return (angle + math.pi) % (2.0 * math.pi) - math.pi

    def _sample_reference(self, count):
        u = np.arange(count, dtype=float) * self.n / count
        i = np.floor(u).astype(int)
        f = (u - i)[:, None]
        j = (i + 1) % self.n
        c = self.C[i] * (1.0 - f) + self.C[j] * f
        normals = self.normals[i] * (1.0 - f) + self.normals[j] * f
        normals /= np.maximum(np.linalg.norm(normals, axis=1), 1e-12)[:, None]
        return c, normals

    @staticmethod
    def _metric(p):
        a = p - np.roll(p, 1, axis=0)
        b = np.roll(p, -1, axis=0) - p
        la = np.maximum(np.linalg.norm(a, axis=1), 1e-9)
        lb = np.maximum(np.linalg.norm(b, axis=1), 1e-9)
        chord = a + b
        lc = np.maximum(np.linalg.norm(chord, axis=1), 1e-9)
        k = 2.0 * (a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) / (la * lb * lc)
        return a, b, la, lb, chord, lc, k

    def _line_energy(self, c, normals, d):
        p = c + normals * d[:, None]
        _, _, la, lb, _, _, k = self._metric(p)
        return float(np.sum(k * k * (la + lb) * 0.5) + 0.00004 * np.sum(lb))

    def _smooth_line(self, c, normals, d, iterations, outer_iterations):
        previous_normals = np.roll(normals, 1, axis=0)
        next_normals = np.roll(normals, -1, axis=0)
        d = np.clip(d, -self.bound, self.bound)

        for _ in range(outer_iterations):
            p = c + normals * d[:, None]
            a, b, la, lb, chord, lc, k = self._metric(p)
            denominator = la * lb * lc

            da = (
                2.0 * np.column_stack((b[:, 1], -b[:, 0])) / denominator[:, None]
                - k[:, None]
                * (a / (la * la)[:, None] + chord / (lc * lc)[:, None])
            )
            db = (
                2.0 * np.column_stack((-a[:, 1], a[:, 0])) / denominator[:, None]
                - k[:, None]
                * (b / (lb * lb)[:, None] + chord / (lc * lc)[:, None])
            )

            ca = np.sum(-da * previous_normals, axis=1)
            cb = np.sum((da - db) * normals, axis=1)
            cc = np.sum(db * next_normals, axis=1)
            constant = k - ca * np.roll(d, 1) - cb * d - cc * np.roll(d, -1)
            weight = 0.5 * (la + lb)

            # Derivative of arc-length weighting, including the length term.
            edge_weight = 0.00004 + 0.5 * (k * k + np.roll(k * k, -1))
            length_gradient = np.sum(
                normals
                * (
                    np.roll(edge_weight, 1)[:, None] * a / la[:, None]
                    - edge_weight[:, None] * b / lb[:, None]
                ),
                axis=1,
            )

            sw = np.sqrt(weight)
            aa, bb, cc_abs = abs(ca) * sw, abs(cb) * sw, abs(cc) * sw
            row_norm = float(np.max(aa + bb + cc_abs))
            col_norm = float(
                np.max(bb + np.roll(aa, -1) + np.roll(cc_abs, 1))
            )
            step = 0.48 / max(row_norm * col_norm, 1e-12)

            x = d.copy()
            y = x.copy()
            momentum = 1.0
            for _iteration in range(iterations):
                residual = (
                    constant + ca * np.roll(y, 1) + cb * y + cc * np.roll(y, -1)
                )
                wr = weight * residual
                gradient = 2.0 * (
                    cb * wr + np.roll(ca * wr, -1) + np.roll(cc * wr, 1)
                ) + length_gradient
                new_x = np.clip(y - step * gradient, -self.bound, self.bound)
                new_momentum = 0.5 * (1.0 + math.sqrt(1.0 + 4.0 * momentum**2))
                y = new_x + ((momentum - 1.0) / new_momentum) * (new_x - x)
                x = new_x
                momentum = new_momentum

            old_energy = self._line_energy(c, normals, d)
            fraction = 1.0
            for _trial in range(7):
                candidate = d + fraction * (x - d)
                if self._line_energy(c, normals, candidate) <= old_energy + 1e-12:
                    d = candidate
                    break
                fraction *= 0.5
        return d

    def _quick_time(self, c, normals, d):
        p = c + normals * d[:, None]
        _, _, _, ds, _, _, k = self._metric(p)
        cap = np.minimum(
            110.0**2,
            self.plan_grip * self.g0
            / np.maximum(np.abs(k) - self.plan_grip * self.g2, 1e-10),
        )
        cap = np.r_[cap, cap[0]]

        # Analytic backward envelope for a conservative, nearly constant
        # fraction of total tyre grip. Saturation scrub is used by the controller.
        b0 = 0.83 * self.g0 + self.drag0
        b2 = 0.83 * self.g2 + self.drag2
        distance = np.r_[0.0, np.cumsum(ds)]
        exponential = np.exp(2.0 * b2 * distance)
        transformed = (cap + b0 / b2) * exponential
        backward = (
            np.minimum.accumulate(transformed[::-1])[::-1] / exponential - b0 / b2
        )

        km = 0.5 * (np.abs(k) + np.abs(np.roll(k, -1)))
        w = 0.0
        elapsed = 0.0
        for h, curvature, limit in zip(
            ds.tolist(), km.tolist(), backward[1:].tolist()
        ):
            g = self.g0 + self.g2 * w
            lateral = curvature * w
            traction = math.sqrt(max(0.0, g * g - lateral * lateral))
            force = min(
                self.drive_acc, self.power_acc / max(math.sqrt(w), 1.0),
                0.99 * traction,
            )
            acceleration = force - self.drag0 - self.drag2 * w
            midpoint_w = max(0.0, w + h * acceleration)
            g = self.g0 + self.g2 * midpoint_w
            lateral = curvature * midpoint_w
            traction = math.sqrt(max(0.0, g * g - lateral * lateral))
            force = min(
                self.drive_acc,
                self.power_acc / max(math.sqrt(midpoint_w), 1.0),
                0.99 * traction,
            )
            acceleration = force - self.drag0 - self.drag2 * midpoint_w
            new_w = min(limit, max(0.001, w + 2.0 * h * acceleration))
            elapsed += 2.0 * h / max(math.sqrt(w) + math.sqrt(new_w), 0.01)
            w = new_w

        elapsed += 18.0 * float(np.sum((k - np.roll(k, 1)) ** 2))
        return elapsed

    def _time_polish(self, full_offset):
        count = max(100, self.n // 3)
        c, normals = self._sample_reference(count)
        u = np.arange(count, dtype=float) * self.n / count
        d = np.interp(
            u, np.arange(self.n + 1), np.r_[full_offset, full_offset[0]]
        )
        coarse_s = np.arange(count, dtype=float) * self.length / count
        full_s = np.arange(self.n, dtype=float) * self.length / self.n
        result = full_offset.copy()
        best_time = self._quick_time(c, normals, d)

        for radius, amount in ((80.0, 0.16), (44.0, 0.12)):
            _, _, _, _, _, _, filter_k = self._metric(c + normals * d[:, None])
            for center in np.arange(0.0, self.length, 36.0):
                distance = (
                    coarse_s - center + 0.5 * self.length
                ) % self.length - 0.5 * self.length
                indices = np.flatnonzero(np.abs(distance) < radius)
                if len(indices) == 0 or np.max(np.abs(filter_k[indices])) < 0.0007:
                    continue

                bell = (0.5 + 0.5 * np.cos(math.pi * distance[indices] / radius)) ** 2
                mixing = amount * bell
                chosen = None
                chosen_sign = 0.0
                chosen_time = best_time
                for sign in (-1.0, 1.0):
                    change = mixing * (sign * self.bound - d[indices])
                    if np.max(np.abs(change)) < 0.025:
                        continue
                    candidate = d.copy()
                    candidate[indices] += change
                    lap_time = self._quick_time(c, normals, candidate)
                    if lap_time < chosen_time - 0.0001:
                        chosen = candidate
                        chosen_time = lap_time
                        chosen_sign = sign

                if chosen is not None:
                    d = chosen
                    best_time = chosen_time
                    distance_full = (
                        full_s - center + 0.5 * self.length
                    ) % self.length - 0.5 * self.length
                    ix = np.flatnonzero(np.abs(distance_full) < radius)
                    bell_full = (
                        0.5 + 0.5 * np.cos(math.pi * distance_full[ix] / radius)
                    ) ** 2
                    result[ix] += amount * bell_full * (
                        chosen_sign * self.bound - result[ix]
                    )
        return result

    def _make_geometry(self, p):
        a, b, la, lb, _, _, k = self._metric(p)
        tangent = a / la[:, None] + b / lb[:, None]
        heading = np.arctan2(tangent[:, 1], tangent[:, 0])
        return {
            "points": p,
            "vectors": b,
            "ds": lb,
            "length2": lb * lb,
            "heading": heading,
            "curvature": k,
        }

    def _maximum_braking(self, w, curvature):
        g = self.g0 + self.g2 * w
        q = min(0.999, max(0.0, curvature * w / g))
        r = math.sqrt(max(1e-8, 1.0 - q * q))
        demand_limit = min(
            g / r, w * self.plan_steer_curvature / max(q, 1e-10)
        )
        tyre_braking = g * r + self.scrub * max(0.0, demand_limit - g)
        return 0.90 * tyre_braking + self.drag0 + self.drag2 * w

    def _speed_profile(self, k, ds, finish_curvature):
        next_k = np.roll(k, -1)
        next_k[-1] = finish_curvature
        km = 0.5 * (np.abs(k) + np.abs(next_k))
        cap = np.minimum(
            110.0**2,
            self.plan_grip * self.g0
            / np.maximum(np.abs(k) - self.plan_grip * self.g2, 1e-10),
        )
        finish_cap = min(
            110.0**2,
            self.plan_grip * self.g0
            / max(abs(finish_curvature) - self.plan_grip * self.g2, 1e-10),
        )
        backward = np.r_[cap, finish_cap]

        for i in range(self.n - 1, -1, -1):
            following = float(backward[i + 1])
            limit = float(cap[i])
            if limit <= following:
                backward[i] = limit
                continue
            h = float(ds[i])
            curvature = float(km[i])
            guess = min(
                limit,
                following + 2.0 * h * (
                    self.g0 + self.g2 * following
                    + self.drag0 + self.drag2 * following
                ),
            )
            previous = guess
            for _ in range(4):
                previous = guess
                midpoint = 0.5 * (following + guess)
                guess = min(
                    limit,
                    following + 2.0 * h * self._maximum_braking(midpoint, curvature),
                )
            backward[i] = min(guess, previous)

        speed2 = np.empty(self.n + 1)
        speed2[0] = 0.0
        for i in range(self.n):
            w = float(speed2[i])
            h = float(ds[i])
            curvature = float(km[i])
            limit = float(backward[i + 1])
            guess = min(limit, w + 2.0 * h * self.drive_acc)
            for _ in range(3):
                midpoint = max(0.0, 0.5 * (w + guess))
                g = self.g0 + self.g2 * midpoint
                lateral = curvature * midpoint
                available = math.sqrt(max(0.0, g * g - lateral * lateral))
                drive = min(
                    self.drive_acc,
                    self.power_acc / max(math.sqrt(midpoint), 1.0),
                    0.99 * available,
                )
                acceleration = drive - self.drag0 - self.drag2 * midpoint
                guess = min(limit, max(0.001, w + 2.0 * h * acceleration))
            speed2[i + 1] = guess

        acceleration = (speed2[1:] - speed2[:-1]) / (2.0 * ds)
        return speed2, acceleration

    def _project(self, geometry, obs, launch):
        segment = int(obs["segment_index"])
        if launch and float(obs["s"]) > self.length - 15.0:
            segment = 0
        if launch:
            indices = np.arange(
                max(0, segment - 12), min(self.n, segment + 13), dtype=int
            )
        else:
            indices = (segment + self.local_indices) % self.n

        position = np.array([float(obs["x"]), float(obs["y"])])
        relative = position - geometry["points"][indices]
        vectors = geometry["vectors"][indices]
        fraction = np.clip(
            np.sum(relative * vectors, axis=1) / geometry["length2"][indices],
            0.0, 1.0,
        )
        residual = relative - fraction[:, None] * vectors
        best = int(np.argmin(np.sum(residual * residual, axis=1)))
        i = int(indices[best])
        f = float(fraction[best])
        h0 = float(geometry["heading"][i])
        h1 = float(geometry["heading"][(i + 1) % self.n])
        heading = h0 + f * self._wrap(h1 - h0)
        foot = geometry["points"][i] + f * geometry["vectors"][i]
        error = (
            -math.sin(heading) * (position[0] - foot[0])
            + math.cos(heading) * (position[1] - foot[1])
        )
        return i, f, heading, float(error)

    def _advance(self, geometry, i, f, distance):
        along = f * float(geometry["ds"][i]) + max(0.0, distance)
        for _ in range(20):
            h = float(geometry["ds"][i])
            if along <= h:
                return i, along / h
            along -= h
            i = (i + 1) % self.n
        return i, 0.0

    def _simulate_controls(self, steer, force, speed, angle, g0, g2, extra_drag,
                           grip_start, drive_start):
        command = steer * self.max_steer
        throttle = max(0.0, force) * grip_start / drive_start
        brake = max(0.0, -force)
        yaw = 0.0
        step_angle = self.steer_rate * self.dt

        for _ in range(self.steps):
            angle += max(-step_angle, min(step_angle, command - angle))
            g = g0 + g2 * speed * speed
            drive = min(self.drive_acc, self.power_acc / max(speed, 1.0))
            longitudinal = throttle * drive - brake * g
            lateral = speed * speed * math.tan(angle) / self.wheelbase
            demand = math.hypot(longitudinal, lateral)
            excess = max(0.0, demand - g)
            if demand > g:
                ratio = g / demand
                longitudinal *= ratio
                lateral *= ratio
            if speed > 1e-8:
                yaw += lateral / speed * self.dt
            drag = self.drag0 + self.drag2 * speed * speed + extra_drag
            speed = max(
                0.0,
                speed + (longitudinal - self.scrub * excess - drag) * self.dt,
            )
        return speed, yaw

    def _commands(self, speed, actual_angle, curvature, net_acceleration, gravel):
        mu = self.mu_gravel if gravel else self.mu
        g0 = mu * 9.81
        g2 = mu * self.down
        extra_drag = self.gravel_drag if gravel else 0.0
        grip_start = g0 + g2 * speed * speed
        drive_start = min(self.drive_acc, self.power_acc / max(speed, 1.0))

        # Cap a feedback-induced lateral demand before it can turn a small
        # tracking error into sustained understeer.
        denominator = abs(curvature) - 0.985 * g2
        if denominator > 1e-10:
            lateral_speed = math.sqrt(0.985 * g0 / denominator)
            if speed > lateral_speed:
                net_acceleration = min(
                    net_acceleration, 5.0 * (lateral_speed - speed)
                )

        net_acceleration = max(-160.0, min(self.drive_acc, net_acceleration))
        midpoint_speed = max(0.1, speed + 0.5 * self.control_dt * net_acceleration)
        w = midpoint_speed * midpoint_speed
        g = g0 + g2 * w
        drag = self.drag0 + self.drag2 * w + extra_drag
        drive_mid = min(self.drive_acc, self.power_acc / max(midpoint_speed, 1.0))

        signed_lateral = w * curvature
        q = min(0.997, abs(signed_lateral) / g)
        sign = -1.0 if signed_lateral < 0.0 else 1.0
        lateral = sign * q * g
        used_curvature = lateral / w
        r = math.sqrt(max(1e-9, 1.0 - q * q))
        long_limit = g * r
        wanted_longitudinal = net_acceleration + drag

        if wanted_longitudinal >= -long_limit:
            requested_long = min(wanted_longitudinal, long_limit, drive_mid)
            requested_lat = lateral
            achievable_acceleration = requested_long - drag
        else:
            # Invert the actual saturated friction-circle model. This preserves
            # the requested turning acceleration while using excess-demand
            # scrub for braking, rather than accepting ordinary brake understeer.
            demand = g + (-wanted_longitudinal - long_limit) / max(self.scrub, 1e-9)
            max_lat_request = w * math.tan(self.max_steer) / self.wheelbase
            demand_limit = min(g / r, max_lat_request / max(q, 1e-10))
            demand = max(g, min(demand, demand_limit))
            requested_long = -r * demand
            requested_lat = sign * q * demand
            achievable_acceleration = (
                -long_limit - self.scrub * (demand - g) - drag
            )

        desired_angle = math.atan(self.wheelbase * requested_lat / w)
        if requested_long >= 0.0:
            throttle = min(1.0, requested_long / drive_mid)
            force = throttle * drive_start / grip_start
        else:
            force = -min(1.0, -requested_long / g)

        # Invert the five-step mean steering slew, then refine with the exact
        # five-step model. Commands beyond the reachable endpoint are redundant.
        difference = desired_angle - actual_angle
        increment = self.steer_rate * self.dt
        magnitude = abs(difference)
        command_change = magnitude
        for reached in range(self.steps):
            candidate = (
                self.steps * magnitude
                - increment * reached * (reached + 1) * 0.5
            ) / (self.steps - reached)
            if candidate <= (reached + 1) * increment + 1e-12:
                command_change = max(0.0, candidate)
                break
        else:
            command_change = self.steps * increment

        command_angle = actual_angle + math.copysign(command_change, difference)
        reachable = self.steer_rate * self.control_dt
        steer_low = max(-1.0, (actual_angle - reachable) / self.max_steer)
        steer_high = min(1.0, (actual_angle + reachable) / self.max_steer)
        steer = max(steer_low, min(steer_high, command_angle / self.max_steer))
        force_high = drive_start / grip_start
        force = max(-1.0, min(force_high, force))

        target_speed = max(0.0, speed + achievable_acceleration * self.control_dt)
        mean_speed = max(0.1, 0.5 * (speed + target_speed))
        target_yaw = mean_speed * used_curvature * self.control_dt
        yaw_weight = 2.5 * max(mean_speed, 5.0)

        def evaluate(s, f):
            predicted_speed, predicted_yaw = self._simulate_controls(
                s, f, speed, actual_angle, g0, g2, extra_drag,
                grip_start, drive_start,
            )
            r0 = predicted_speed - target_speed
            r1 = yaw_weight * (predicted_yaw - target_yaw)
            return r0, r1, r0 * r0 + r1 * r1

        residual0, residual1, cost = evaluate(steer, force)
        for _ in range(3):
            if cost < 1e-10:
                break
            ds = 0.001 if steer + 0.001 <= steer_high else -0.001
            df = 0.002 if force + 0.002 <= force_high else -0.002
            s0, s1, _ = evaluate(steer + ds, force)
            f0, f1, _ = evaluate(steer, force + df)
            j00 = (s0 - residual0) / ds
            j10 = (s1 - residual1) / ds
            j01 = (f0 - residual0) / df
            j11 = (f1 - residual1) / df

            h00 = j00 * j00 + j10 * j10 + 1e-6
            h11 = j01 * j01 + j11 * j11 + 1e-6
            h01 = j00 * j01 + j10 * j11
            b0 = j00 * residual0 + j10 * residual1
            b1 = j01 * residual0 + j11 * residual1
            determinant = max(1e-12, h00 * h11 - h01 * h01)
            change_s = (-b0 * h11 + b1 * h01) / determinant
            change_f = (-b1 * h00 + b0 * h01) / determinant
            change_s = max(-0.25, min(0.25, change_s))
            change_f = max(-0.4, min(0.4, change_f))

            accepted = False
            for scale in (1.0, 0.5, 0.25):
                trial_s = max(steer_low, min(steer_high, steer + scale * change_s))
                trial_f = max(-1.0, min(force_high, force + scale * change_f))
                r0, r1, trial_cost = evaluate(trial_s, trial_f)
                if trial_cost < cost:
                    steer, force = trial_s, trial_f
                    residual0, residual1, cost = r0, r1, trial_cost
                    accepted = True
                    break
            if not accepted:
                break

        throttle = max(0.0, force) * grip_start / drive_start
        brake = max(0.0, -force)
        return (
            float(max(-1.0, min(1.0, steer))),
            float(max(0.0, min(1.0, throttle))),
            float(max(0.0, min(1.0, brake))),
        )

    def act(self, obs: dict) -> tuple[float, float, float]:
        speed = max(0.0, float(obs["speed"]))
        progress = float(obs["lap_progress"])
        launch = progress < 0.1 and (
            float(obs["s"]) < 175.0
            or (progress < 0.005 and float(obs["s"]) > self.length - 15.0)
        )
        geometry = self.launch if launch else self.main
        i, f, path_heading, lateral_error = self._project(geometry, obs, launch)

        next_i = (i + 1) % self.n
        current_curvature = (
            (1.0 - f) * float(geometry["curvature"][i])
            + f * float(geometry["curvature"][next_i])
        )
        heading_error = self._wrap(
            float(obs["heading"]) - path_heading
            + 0.5 * self.dt * speed * current_curvature
        )

        j, jf = self._advance(
            geometry, i, f, 0.5 * self.control_dt * speed
        )
        preview_curvature = (
            (1.0 - jf) * float(geometry["curvature"][j])
            + jf * float(geometry["curvature"][(j + 1) % self.n])
        )
        look = 4.5 + 0.16 * speed
        curvature = (
            preview_curvature * math.cos(heading_error)
            / max(0.65, 1.0 - current_curvature * lateral_error)
            - 2.0 * heading_error / look
            - lateral_error / (look * look)
        )

        finishing_wrap = progress > 0.95 and i < 12
        if finishing_wrap:
            reference_speed = math.sqrt(float(self.speed2[-1]))
            feedforward = (
                min(self.drive_acc, self.power_acc / max(speed, 1.0))
                - self.drag0 - self.drag2 * speed * speed
            )
        else:
            reference_speed = math.sqrt(
                max(0.0, (1.0 - f) * self.speed2[i] + f * self.speed2[i + 1])
            )
            if progress > 0.95 and j < 12:
                feedforward = float(self.acceleration[-1])
            else:
                feedforward = float(self.acceleration[j])

        error_speed_factor = max(
            0.75,
            1.0
            - 0.035 * max(0.0, abs(lateral_error) - 0.45)
            - 0.12 * max(0.0, abs(heading_error) - 0.06),
        )
        reference_speed *= error_speed_factor
        gravel = bool(obs["on_gravel"])
        if gravel:
            reference_speed = min(reference_speed, max(10.0, 0.80 * speed))
            feedforward = min(feedforward, -3.0)

        acceleration = feedforward + 3.8 * (reference_speed - speed)
        return self._commands(
            speed,
            float(obs["steer_angle"]),
            curvature,
            acceleration,
            gravel,
        )
