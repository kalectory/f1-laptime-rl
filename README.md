# F1 lap-time RL

An RL environment where a language model writes the **driving policy for a simulated Formula 1 car as Python code**, and the reward is lap time. We used it to train Qwen3.6-35B-A3B on the [Trajectory](https://trajectory.ai) platform.

https://github.com/rmalde/f1-laptime-rl/raw/main/media/showcase.mp4

*Four cars on the same clock: Qwen after RL (76.1 s), Claude Opus 5.5 (85.9 s), a hand-written centerline baseline (87.2 s), and untrained Qwen (174.6 s). Download [`media/replay.html`](media/replay.html) for the interactive version, which includes every car's code.*

## The task

- **One fixed track.** The Trajectory Grand Prix Circuit is 5.35 km long, with a 1 km main straight, a hairpin, esses, a chicane and a fast sweeper.
- **Same start every time.** Each rollout is a standing start from the same grid slot.
- **What the model writes.** One response, with a 16k output-token budget. It must contain a `class Policy` with `act(obs) -> (steer, throttle, brake)`, called at 20 Hz.
- **Physics.** A kinematic bicycle model with a friction-circle grip limit, aerodynamic downforce and drag, a power limit and a steering slew limit. The exact equations are given in the prompt so the model can plan a racing line and speed profile.
- **Track limits.** Beyond the 12 m of asphalt there is 5 m of gravel on each side (legal, but slow), then a wall. Hitting the wall ends the lap (DNF).
- **Reward** (0 to 1) = `0.5 * progress + 0.5 * time_score`.
  - `progress` is the fraction of the lap completed.
  - `time_score` falls linearly from 1 at a 60 s lap to 0 at 180 s, and is only earned by finishing.
  - Any finished lap therefore beats any crash, and faster beats slower.
- **Sandbox.** The model's code runs in a separate, unprivileged process with a scrubbed environment and CPU and time limits. It can read observations and return actions, but it can't touch the simulator, the lap timer, or API credentials.

## Results

40 rollouts per model. Reward is the mean of the 0–1 reward above.

| Model | Mean reward | Laps finished | Best lap |
|---|---|---|---|
| Qwen3.6-35B-A3B, untrained | 0.026 | 1/40 | 174.6 s |
| Qwen3.6-35B-A3B, after 100 GRPO-style steps | **0.333** | **10/40** | **76.1 s**\* |
| Claude Opus 5.5 (3 rollouts) | 0.883 | 3/3 | 85.9 s |
| Hand-written centerline + speed-profile baseline | — | — | 87.2 s |

\* Fastest lap from the final steps of training (step 94). The step-100 eval's own best was 87.0 s.

**How the training went:**
- **First the model learned to write code that runs.** Python errors plus empty or truncated responses fell from 33/40 to about 3/40.
- **Then it learned to stop crashing.** The finish rate rose steadily: 7% → 13% → 18% → 23% of training rollouts.
- **Peak speed came early.** Laps of about 76 s appeared from step 30 onward. Most of the later gains are reliability.

Training: Qwen3.6-35B-A3B, GSPO, 8 groups × 16 samples per step, learning rate 1e-4, 100 steps.

## Repo layout

```
runtime/                 # everything that runs inside the eval container
  f1env/track.py         # the circuit (closed Catmull-Rom spline, 2 m resampling)
  f1env/physics.py       # car model
  f1env/sim.py           # headless lap runner + sandboxed policy process + reward
  f1env/policy_host.py   # child process that hosts untrusted policy code
  f1env/prompt.py        # the task prompt + code extraction
  f1env/render.py        # graphics mode: HTML replay (map, onboard cam, corner close-ups, code viewer)
  f1env/rollout.py       # one rollout: prompt → code → lap → reward (Trajectory SDK)
  harness.py, Dockerfile # container entrypoint for the Trajectory platform
f1.py                    # local CLI: sim / rollout / replay
platform_eval.py         # register benchmark, run evals, launch/resume training
analyze_training.py      # re-simulate sampled training rollouts per step (failure breakdown)
compare.py               # overlay several evals + policies in one replay
make_showcase.py         # best lap vs baselines → replay (+ video)
record_video.py          # replay HTML → MP4 (headless Chromium + ffmpeg)
examples/                # model-written policies (Opus, Qwen before/after RL)
policies/                # hand-written baselines + sandbox sanity checks
```

## Quickstart

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# physics only (headless, ~0.3 s per lap)
.venv/bin/python f1.py sim examples/*.py policies/baseline_centerline.py

# graphics: same, plus an HTML replay with every car on the same clock
.venv/bin/python f1.py sim examples/*.py --render
```

With a `TRAJECTORY_API_KEY`:

```bash
.venv/bin/python f1.py rollout --model anthropic/claude-opus-5.5 -n 3 --render   # local rollouts
.venv/bin/python platform_eval.py push                                            # register benchmark + build image
.venv/bin/python platform_eval.py eval --model Qwen/Qwen3.6-35B-A3B -n 40
.venv/bin/python platform_eval.py train --steps 10 --batch 8 --group 16
.venv/bin/python f1.py replay --eval-id <eval_run_id> --render                    # pull rollouts, re-sim, render
```

The simulator is deterministic, so re-running a rollout's code locally reproduces the lap time the trainer saw.

To record a video (needs Playwright with Chromium, and ffmpeg):

```bash
.venv/bin/python -m playwright install chromium
.venv/bin/python record_video.py media/replay.html out.mp4 --speed 5
```
