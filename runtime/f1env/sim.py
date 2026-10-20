"""Run one timed lap of a policy file. Headless; returns a result dict with a trace.

The policy runs in a separate, unprivileged child process with a scrubbed environment,
so it can read observations and return actions but cannot touch simulator state, the
lap timer, or the harness's API credentials.
"""

from __future__ import annotations

import json
import math
import os
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from f1env.physics import CarParams, CarState, step
from f1env.track import get_track

MAX_LAP_TIME = 180.0  # s of simulated time before the run is declared a DNF
INIT_TIMEOUT = 30.0  # s wall clock for Policy.__init__
STEP_TIMEOUT = 1.0  # s wall clock for a single act() call
TOTAL_ACT_BUDGET = 60.0  # s wall clock summed over all act() calls
STALL_SECONDS = 10.0  # DNF if the car sits below 0.5 m/s this long (after the first 5 s)
_HOST = Path(__file__).with_name("policy_host.py")


class PolicyFailure(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


class _PolicyProcess:
    def __init__(self, policy_path: Path):
        self.tmp = tempfile.mkdtemp(prefix="f1policy-")
        os.chmod(self.tmp, 0o755)
        code_path = Path(self.tmp) / "policy.py"
        shutil.copy(policy_path, code_path)
        os.chmod(code_path, 0o644)
        self.stderr_path = Path(self.tmp) / "stderr.txt"
        self._stderr = open(self.stderr_path, "wb")
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": self.tmp,
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-I", str(_HOST), str(code_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            env=env,
            cwd=self.tmp,
            preexec_fn=_sandbox_child,
        )
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.proc.stdout, selectors.EVENT_READ)
        self.buf = b""

    def request(self, msg: dict, timeout: float) -> dict:
        try:
            self.proc.stdin.write((json.dumps(msg) + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise PolicyFailure("policy_crashed", self.stderr_tail())
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PolicyFailure("policy_timeout", f"no reply within {timeout:.2f}s")
            if not self.sel.select(remaining):
                continue
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                raise PolicyFailure("policy_crashed", self.stderr_tail())
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        reply = json.loads(line)
        if "error" in reply:
            raise PolicyFailure("policy_error", reply["error"])
        return reply

    def stderr_tail(self, n: int = 2000) -> str:
        try:
            self._stderr.flush()
            return self.stderr_path.read_bytes()[-n:].decode(errors="replace")
        except OSError:
            return ""

    def close(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        self._stderr.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def _sandbox_child() -> None:
    import resource

    os.setsid()
    resource.setrlimit(resource.RLIMIT_CPU, (150, 150))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
    if os.geteuid() == 0:  # in the eval container: drop to nobody
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)


def _clip(v, lo, hi):
    if not isinstance(v, float) or math.isnan(v):
        return 0.0
    return lo if v < lo else hi if v > hi else v


def run_lap(policy_path: str | Path, record_trace: bool = True) -> dict:
    track = get_track()
    car = CarParams()
    start = track.to_dict()["start"]
    st = CarState(x=start["x"], y=start["y"], heading=start["heading"])
    seg, s0, d = track.project(st.x, st.y, 0)

    result = {
        "finished": False,
        "lap_time": None,
        "reason": None,
        "detail": "",
        "progress": 0.0,
        "sim_time": 0.0,
        "max_speed_kph": 0.0,
        "gravel_time": 0.0,
        "track_length": track.length,
    }
    trace: list[list[float]] = []
    proc = _PolicyProcess(Path(policy_path))
    act_wall = 0.0
    try:
        proc.request({"init": {"track": track.to_dict(), "car": car.to_dict()}}, INIT_TIMEOUT)
        t = 0.0
        s_total = 0.0  # unwrapped progress along the centerline
        prev_s = s0
        stalled = 0.0
        substeps = round(car.control_dt / car.physics_dt)
        while True:
            s_lap = s_total % track.length if s_total >= 0 else s_total
            th = track.heading[seg]
            on_gravel = abs(d) > track.half_width
            obs = {
                "t": t,
                "x": st.x,
                "y": st.y,
                "heading": st.heading,
                "speed": st.speed,
                "yaw_rate": st.yaw_rate,
                "steer_angle": st.steer_angle,
                "s": s_lap,
                "lap_progress": s_total / track.length,
                "lateral_offset": d,
                "track_heading": th,
                "heading_error": (st.heading - th + math.pi) % (2 * math.pi) - math.pi,
                "segment_index": seg,
                "on_gravel": on_gravel,
            }
            t0 = time.monotonic()
            reply = proc.request({"obs": obs}, STEP_TIMEOUT)
            act_wall += time.monotonic() - t0
            if act_wall > TOTAL_ACT_BUDGET:
                raise PolicyFailure("policy_timeout", f"act() used more than {TOTAL_ACT_BUDGET:.0f}s total")
            steer = _clip(reply["a"][0], -1.0, 1.0)
            throttle = _clip(reply["a"][1], 0.0, 1.0)
            brake = _clip(reply["a"][2], 0.0, 1.0)
            if record_trace:
                trace.append([round(t, 2), round(st.x, 2), round(st.y, 2), round(st.heading, 4),
                              round(st.speed, 2), round(steer, 3), round(throttle, 3), round(brake, 3), round(d, 2), round(s_total, 1)])

            for _ in range(substeps):
                step(st, car, steer, throttle, brake, on_gravel)
                t += car.physics_dt
                seg, s_new, d = track.project(st.x, st.y, seg)
                ds = (s_new - prev_s + track.length / 2) % track.length - track.length / 2
                prev_s = s_new
                s_total += ds
                on_gravel = abs(d) > track.half_width
                if on_gravel:
                    result["gravel_time"] += car.physics_dt
                result["max_speed_kph"] = max(result["max_speed_kph"], st.speed * 3.6)
                if s_total >= track.length:
                    # interpolate the exact crossing inside this substep
                    over = (s_total - track.length) / max(ds, 1e-9)
                    result.update(finished=True, lap_time=t - over * car.physics_dt, reason="finished")
                    break
                if abs(d) > track.wall:
                    result.update(reason="crash", detail=f"hit the wall at s={s_new:.0f} m, t={t:.2f}s")
                    break
            if result["reason"]:
                break
            stalled = stalled + car.control_dt if (st.speed < 0.5 and t > 5.0) else 0.0
            if stalled >= STALL_SECONDS:
                result.update(reason="stalled", detail=f"car stopped at s={s_total:.0f} m")
                break
            if t >= MAX_LAP_TIME:
                result.update(reason="time_limit", detail=f"no lap within {MAX_LAP_TIME:.0f}s")
                break
        result["sim_time"] = t
        result["progress"] = max(0.0, min(1.0, s_total / track.length))
    except PolicyFailure as e:
        result.update(reason=e.reason, detail=(e.detail + "\n" + proc.stderr_tail(800))[-2500:])
    finally:
        result["policy_stdout_tail"] = proc.stderr_tail(1500)
        proc.close()
    if result["finished"]:
        result["progress"] = 1.0
    if record_trace:
        result["trace"] = trace
    result["reward"] = reward_from_result(result)
    return result


TIME_ZERO = MAX_LAP_TIME  # lap time scoring 0 on the time component
TIME_FULL = 60.0  # lap time scoring 1 (faster than this car can physically go)
W_PROGRESS = 0.5
W_TIME = 0.5


def progress_score(result: dict) -> float:
    """Fraction of the lap completed, 0..1 (1.0 for a finished lap)."""
    return 1.0 if result["finished"] else max(0.0, min(1.0, result["progress"]))


def time_score(result: dict) -> float:
    """Linear in lap time: 180 s -> 0, 60 s -> 1. Zero unless the lap was completed."""
    if not (result["finished"] and result["lap_time"]):
        return 0.0
    return max(0.0, min(1.0, (TIME_ZERO - result["lap_time"]) / (TIME_ZERO - TIME_FULL)))


def reward_from_result(result: dict) -> float:
    """0.5 * progress + 0.5 * time, in [0, 1].

    A DNF scores at most 0.5 (progress only); every finished lap scores >= 0.5 plus its
    time score, so finishing always beats crashing and faster always beats slower.
    """
    return W_PROGRESS * progress_score(result) + W_TIME * time_score(result)
