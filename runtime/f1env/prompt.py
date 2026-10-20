"""The task prompt and the code extractor. One fixed prompt: every rollout sees the same task."""

from __future__ import annotations

import re

from f1env.physics import CarParams
from f1env.sim import INIT_TIMEOUT, MAX_LAP_TIME, STEP_TIMEOUT, TOTAL_ACT_BUDGET
from f1env.track import CONTROL_POINTS, GRAVEL_WIDTH, HALF_WIDTH, get_track

SYSTEM_PROMPT = (
    "You are an expert motorsport control engineer and Python programmer. "
    "You write a complete, self-contained driving policy that is executed in a simulator. "
    "Your response must end with exactly one ```python code block containing the full policy. "
    "Types: track['centerline'] is a list of [x, y] lists; track['spacing'], track['length'], "
    "track['half_width'], track['gravel_width'], track['wall_offset'] and every car[...] value are "
    "single floats (not arrays); obs values are floats except obs['segment_index'] (int) and "
    "obs['on_gravel'] (bool)."
)


def build_user_prompt(max_output_tokens: int = 16384) -> str:
    p = CarParams()
    tr = get_track()
    cps = ", ".join(f"({x:g}, {y:g})" for x, y in CONTROL_POINTS)
    return f"""# Task: write the fastest lap policy for a simulated Formula 1 car

Write a Python class `Policy` that drives one timed lap of a fixed circuit. Reward (0 to 1) is
0.5 * progress + 0.5 * time_score. progress is the fraction of the lap completed (1.0 if you
finish). time_score is earned only by completing the lap: it falls linearly from 1.0 at a 60 s
lap to 0.0 at {MAX_LAP_TIME:.0f} s. Hitting a wall, stalling, erroring, or running out of time ends the
run with no time_score, so any finished lap beats any crash, and faster laps beat slower ones.
Every run starts from the identical state, and the simulator is fully deterministic: same code,
same lap time.

You have a budget of {max_output_tokens} output tokens for this whole response (including any
reasoning). Code that is cut off scores zero, so leave room to finish the code block.

## Interface

```python
class Policy:
    def __init__(self, track: dict, car: dict):
        ...  # precompute anything you like (time limit {INIT_TIMEOUT:.0f} s)

    def act(self, obs: dict) -> tuple[float, float, float]:
        ...  # return (steer, throttle, brake)
```

- `steer` in [-1, 1]: commanded wheel angle = steer * max_steer. Positive steers LEFT
  (counter-clockwise, increases heading).
- `throttle` in [0, 1], `brake` in [0, 1]. Out-of-range values are clipped; NaN becomes 0.
- `act` is called every {p.control_dt} s of simulated time ({1 / p.control_dt:.0f} Hz); the action
  is held for {round(p.control_dt / p.physics_dt)} physics steps of {p.physics_dt} s.
- Compute limits: each `act` call must return within {STEP_TIMEOUT:.0f} s wall clock and all
  `act` calls together within {TOTAL_ACT_BUDGET:.0f} s. Python 3.12 standard library and `numpy`
  are available. No file, network, or subprocess access; print output is discarded.

### `track` (dict)
- `centerline`: list of [x, y] points in meters, ~{tr.length / tr.n:.2f} m apart, forming a
  closed loop in driving order. Point 0 is the start/finish line. {tr.n} points.
- `spacing`: exact arc length between consecutive centerline points (m).
- `length`: lap length along the centerline = {tr.length:.3f} m.
- `half_width`: {HALF_WIDTH} m. Asphalt is |lateral offset| <= {HALF_WIDTH} m from the centerline.
- `gravel_width`: {GRAVEL_WIDTH} m of gravel run-off beyond each asphalt edge.
- `wall_offset`: {HALF_WIDTH + GRAVEL_WIDTH} m. Crossing |lateral offset| > {HALF_WIDTH + GRAVEL_WIDTH} m is a crash (DNF).
- `start`: {{"x": 0, "y": 0, "heading": 0}} (heading in radians, 0 = +x, counter-clockwise positive).

Layout (y is up; the centerline is a centripetal Catmull-Rom spline through these control
points, in driving order, closed back to the first): {cps}.
Main straight runs +x from the start, heavy-braking right hairpin at x~1100, esses heading
west, a long left onto the back straight (y~-455), a chicane at x~1200-1290, a fast left
sweeper north at x~1400, the top straight heading west (y~220), then tight lefts back onto
the main straight. Tightest corner radius on the centerline is ~12.6 m (the chicane).

### `car` (dict) — exact physics parameters
{p.to_dict()}

### `obs` (dict) passed to `act`
- `t`: simulated time (s). `x`, `y`: position (m). `heading`: rad in [-pi, pi).
- `speed`: m/s (never negative; there is no reverse). `yaw_rate`: rad/s.
- `steer_angle`: current actual wheel angle (rad), which lags your command (slew limit).
- `segment_index`: index i of the centerline segment [i, i+1] nearest the car.
- `s`: distance along the centerline (m) of the car's projection, in [0, length).
- `lap_progress`: unwrapped s / length (lap ends when this reaches 1.0).
- `lateral_offset`: signed distance from the centerline (m), positive = LEFT of the driving direction.
- `track_heading`: direction of the current centerline segment (rad).
- `heading_error`: heading - track_heading, wrapped to [-pi, pi).
- `on_gravel`: true if |lateral_offset| > half_width.

## Exact physics (per physics step, dt = {p.physics_dt} s)

The car is a kinematic bicycle (no sideslip) with a friction-circle grip limit:

```
v = speed
# steering actuator: wheel angle moves toward steer*max_steer at most max_steer_rate*dt per step
delta += clip(steer*max_steer - delta, -max_steer_rate*dt, +max_steer_rate*dt)
downforce = 0.5*rho*cla*v^2
N = mass*9.81 + downforce
mu_s = mu (asphalt) or mu_gravel (on gravel)
a_grip = mu_s * N / mass                                  # total acceleration the tyres can give
F_drive = throttle * min(power / max(v, 1), max_drive_force)
F_brake = brake * mu_s * N                                # brake=1 requests all available grip
a_long_req = (F_drive - F_brake) / mass
a_lat_req  = v * (v * tan(delta) / wheelbase)              # = v^2 * curvature of the steered path
demand = hypot(a_long_req, a_lat_req)
if demand > a_grip:                                       # friction circle exceeded
    k = a_grip / demand; a_long = a_long_req*k; a_lat = a_lat_req*k
    excess = demand - a_grip                              # understeer: car runs wide...
else:
    a_long, a_lat, excess = a_long_req, a_lat_req, 0
drag = 0.5*rho*cda*v^2/mass + crr*N/mass (+ gravel_drag on gravel)
v_new = max(0, v + (a_long - scrub*excess)*dt - drag*dt) # ...and scrubs speed
yaw_rate = a_lat / v
heading += yaw_rate*dt
x += v_new*cos(heading)*dt ; y += v_new*sin(heading)*dt
```

Useful consequences: with downforce, grip grows with v^2. On asphalt, any corner of radius
above roughly mass/(0.5*rho*cla*mu) = {p.mass / (0.5 * p.rho * p.cla * p.mu):.0f} m can be taken
at any speed; top speed on a straight is limited by power vs drag (~{352} km/h). The lap is
timed from a standing start (speed 0) at the start/finish line until the car's centerline
progress completes one full lap; the crossing time is interpolated. Time limit {MAX_LAP_TIME:.0f} s.
Cutting the track is impossible: progress is measured along the centerline, and the wall is
{HALF_WIDTH + GRAVEL_WIDTH} m from it. Using the full {2 * HALF_WIDTH:.0f} m of asphalt
(a racing line) is allowed and faster than the centerline. Even the gravel is legal, just slow.

## Output

Think about the approach, then output the complete code in one ```python block at the end of
your response. The block must define `class Policy` and may define helpers. Lap time is all
that matters.
"""


_BLOCK = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str | None:
    """Last fenced block that defines class Policy; else the last block; else None."""
    blocks = _BLOCK.findall(text or "")
    for b in reversed(blocks):
        if "class Policy" in b:
            return b
    # unterminated final block (truncated response): never accept partial code silently
    return None
