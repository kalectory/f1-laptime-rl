"""F1 lap-time eval: local CLI.

  python f1.py sim POLICY.py [POLICY2.py ...] [--render]   physics only; --render adds graphics
  python f1.py rollout --model anthropic/claude-opus-5.5 -n 3 [--render]
                                                           local rollouts via the Trajectory API
  python f1.py replay --eval-id EVAL_RUN_ID [--render]     pull platform rollouts (any model,
                                                           incl. Qwen) and re-simulate / render
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "runtime"))

from f1env.render import render_html  # noqa: E402
from f1env.sim import run_lap  # noqa: E402

OUT = ROOT / "out"


def _fmt(r: dict) -> str:
    if r["finished"]:
        return f"lap {r['lap_time']:.3f}s  reward {r['reward']:.4f}  top {r['max_speed_kph']:.0f} km/h  gravel {r['gravel_time']:.1f}s"
    return f"DNF ({r['reason']}) progress {r['progress'] * 100:.1f}%  reward {r['reward']:.4f}  {r.get('detail', '')[:200]}"


def _open(path: Path) -> None:
    print(f"replay: {path}")
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)


def cmd_sim(args) -> None:
    runs = []
    for p in args.policies:
        r = run_lap(p, record_trace=args.render)
        print(f"{Path(p).name:40s} {_fmt(r)}")
        runs.append({"label": Path(p).stem, "result": r, "code": Path(p).read_text()})
    if args.render:
        _open(render_html(runs, OUT / "sim_replay.html", "F1 Lap Replay — local policies"))


def cmd_rollout(args) -> None:
    from trajectory import Client

    from f1env.rollout import rollout

    client = Client(max_retries=10)
    slug = args.model.replace("/", "_")
    rundir = OUT / f"rollouts_{slug}"
    rundir.mkdir(parents=True, exist_ok=True)
    with cf.ThreadPoolExecutor(args.n) as ex:
        bundles = list(ex.map(lambda _: rollout(client, args.model, args.max_tokens), range(args.n)))
    runs = []
    for i, b in enumerate(bundles, 1):
        s = b["summary"]
        (rundir / f"rollout{i}.json").write_text(json.dumps(b))
        if b["code"]:
            (rundir / f"rollout{i}_policy.py").write_text(b["code"])
        print(f"rollout {i}: {_fmt(b['result'])}  tokens={s['completion_tokens']}  tid={s['tid']}")
        runs.append({"label": f"{args.model} #{i}", "result": b["result"], "code": b["code"], "response": b["response_text"]})
    _summary(args.model, [b["result"] for b in bundles])
    if args.render:
        _open(render_html(runs, rundir / "replay.html", f"F1 Lap Replay — {args.model}"))


def cmd_replay(args) -> None:
    from trajectory import Client

    from f1env.prompt import extract_code

    client = Client(max_retries=10)
    rundir = OUT / f"eval_{args.eval_id}"
    rundir.mkdir(parents=True, exist_ok=True)
    model = args.label or args.eval_id
    runs, results = [], []
    trajs = sorted((t.model_dump() for t in client.trajectories.list(eval_run_id=args.eval_id, limit=100)),
                   key=lambda d: d["created_at"])
    for i, meta in enumerate(trajs, 1):
        tid = meta["trajectory_id"]
        # The model's response lives in the trajectory's steps; the sim is deterministic,
        # so re-running the extracted code locally reproduces the platform lap exactly.
        steps = list(client.trajectories.steps.list(tid))
        msgs = [m for st in steps for m in st.model_dump()["messages"] if m["role"] == "assistant"]
        text = msgs[-1]["content"] if msgs else ""
        code = extract_code(text or "")
        (rundir / f"{tid}_response.md").write_text(text or "")
        if code is None:
            r = {"finished": False, "lap_time": None, "progress": 0.0, "reward": 0.0, "reason": "no_code",
                 "max_speed_kph": 0.0, "gravel_time": 0.0, "detail": "no complete python block", "trace": []}
        else:
            (rundir / f"{tid}_policy.py").write_text(code)
            r = run_lap(rundir / f"{tid}_policy.py")
        toks = msgs[-1].get("completion_tokens") if msgs else None
        print(f"#{i} {tid}: {_fmt(r)}  platform_reward={meta['reward']}  tokens={toks}")
        results.append(r)
        runs.append({"label": f"{model} #{i}", "result": r, "code": code, "response": text})
    _summary(model, results)
    if args.render and runs:
        _open(render_html(runs, rundir / "replay.html", f"F1 Lap Replay — {model}"))


def _summary(model: str, results: list[dict]) -> None:
    laps = [r["lap_time"] for r in results if r["finished"]]
    best = f"best {min(laps):.3f}s" if laps else "no finished laps"
    mean_r = sum(r["reward"] for r in results) / max(1, len(results))
    print(f"== {model}: {len(laps)}/{len(results)} finished, {best}, mean reward {mean_r:.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sim")
    s.add_argument("policies", nargs="+")
    s.add_argument("--render", action="store_true")
    s.set_defaults(fn=cmd_sim)
    r = sub.add_parser("rollout")
    r.add_argument("--model", default="anthropic/claude-opus-5.5")
    r.add_argument("-n", type=int, default=3)
    r.add_argument("--max-tokens", type=int, default=16384)
    r.add_argument("--render", action="store_true")
    r.set_defaults(fn=cmd_rollout)
    p = sub.add_parser("replay")
    p.add_argument("--eval-id", required=True)
    p.add_argument("--label", help="name shown in the replay, e.g. the model slug")
    p.add_argument("--render", action="store_true")
    p.set_defaults(fn=cmd_replay)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
