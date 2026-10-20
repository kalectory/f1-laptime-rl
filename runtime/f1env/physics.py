"""Car model: kinematic bicycle with a friction-circle grip limit, aero, and power limit.

Every equation here is also spelled out in the prompt (f1env/prompt.py), so a policy
can plan an exact speed profile. Keep the two in sync.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

G = 9.81


@dataclass(frozen=True)
class CarParams:
    mass: float = 798.0  # kg, car + driver
    wheelbase: float = 3.6  # m
    max_steer: float = 0.35  # rad, wheel angle at steer = +-1
    max_steer_rate: float = 2.0  # rad/s, steering actuator slew limit
    power: float = 760_000.0  # W, max engine power at the wheels
    max_drive_force: float = 14_000.0  # N, drivetrain force cap (low speed)
    mu: float = 1.8  # tyre friction coefficient on asphalt
    mu_gravel: float = 0.6  # friction coefficient in the gravel run-off
    gravel_drag: float = 3.0  # m/s^2 extra deceleration while in gravel
    rho: float = 1.225  # kg/m^3 air density
    cda: float = 1.25  # m^2 drag area
    cla: float = 3.6  # m^2 downforce (lift) area
    crr: float = 0.012  # rolling resistance coefficient
    scrub: float = 0.4  # extra deceleration per m/s^2 of unmet lateral demand
    physics_dt: float = 0.01  # s
    control_dt: float = 0.05  # s (policy is queried at 20 Hz)

    def to_dict(self):
        return asdict(self)


@dataclass
class CarState:
    x: float
    y: float
    heading: float
    speed: float = 0.0
    steer_angle: float = 0.0  # actual wheel angle (rad), after slew limit
    yaw_rate: float = 0.0
    a_long: float = 0.0
    a_lat: float = 0.0


def step(state: CarState, p: CarParams, steer: float, throttle: float, brake: float, on_gravel: bool) -> None:
    """Advance one physics_dt in place. Inputs already clipped to their ranges."""
    dt = p.physics_dt
    v = state.speed

    # Steering actuator: slew-limited toward the commanded wheel angle.
    target = steer * p.max_steer
    max_d = p.max_steer_rate * dt
    state.steer_angle += max(-max_d, min(max_d, target - state.steer_angle))

    # Vertical load and total grip available.
    downforce = 0.5 * p.rho * p.cla * v * v
    normal = p.mass * G + downforce
    mu = p.mu_gravel if on_gravel else p.mu
    a_grip = mu * normal / p.mass

    # Requested accelerations.
    f_drive = throttle * min(p.power / max(v, 1.0), p.max_drive_force)
    f_brake = brake * mu * normal  # brake = 1 can use all available grip
    a_long_req = (f_drive - f_brake) / p.mass
    yaw_req = v * math.tan(state.steer_angle) / p.wheelbase
    a_lat_req = v * yaw_req

    # Friction circle: if the combined demand exceeds grip, both components are scaled
    # down proportionally (understeer + reduced braking/traction) and the car scrubs speed.
    demand = math.hypot(a_long_req, a_lat_req)
    excess = 0.0
    if demand > a_grip:
        k = a_grip / demand
        excess = demand - a_grip
        a_long, a_lat = a_long_req * k, a_lat_req * k
    else:
        a_long, a_lat = a_long_req, a_lat_req

    drag = 0.5 * p.rho * p.cda * v * v / p.mass + p.crr * normal / p.mass
    if on_gravel:
        drag += p.gravel_drag
    dv = a_long - p.scrub * excess
    v_new = v + dv * dt
    # resistive forces can only slow the car to a stop
    v_new = max(0.0, v_new - drag * dt) if v_new > 0 else 0.0

    yaw = a_lat / v if v > 1e-3 else 0.0
    state.heading = (state.heading + yaw * dt + math.pi) % (2 * math.pi) - math.pi
    state.speed = v_new
    state.x += v_new * math.cos(state.heading) * dt
    state.y += v_new * math.sin(state.heading) * dt
    state.yaw_rate = yaw
    state.a_long = (v_new - v) / dt
    state.a_lat = a_lat
