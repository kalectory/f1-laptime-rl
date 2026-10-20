"""Build the showcase replay (+ video) from a finished eval: best lap of the trained model
vs Opus, the centerline baseline, and untrained Qwen.

  python make_showcase.py EVAL_ID --label "Qwen3.6-35B (100 RL steps)" [--video]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "runtime"))

from f1env.render import render_html  # noqa: E402
from f1env.sim import run_lap  # noqa: E402

OPUS = ROOT / "examples/opus_5_5_best_85.9s.py"
QWEN_BASE = ROOT / "examples/qwen_untrained_174.6s.py"
BASELINE = ROOT / "policies/baseline_centerline.py"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_id")
    ap.add_argument("--label", default="Qwen3.6-35B (RL)")
    ap.add_argument("--video", action="store_true")
    args = ap.parse_args()

    d = ROOT / "out" / f"eval_{args.eval_id}"
    results = []
    for p in sorted(d.glob("*_policy.py")):
        r = run_lap(p)
        results.append((r, p))
    finished = sorted([x for x in results if x[0]["finished"]], key=lambda x: x[0]["lap_time"])
    n = len(list(d.glob("*_response.md")))
    stats = {"rollouts": n, "finished": len(finished),
             "mean_reward": sum(r["reward"] for r, _ in results) / max(n, 1),
             "best_lap": finished[0][0]["lap_time"] if finished else None,
             "best_policy": str(finished[0][1]) if finished else None}
    print(json.dumps(stats))
    (d / "showcase_stats.json").write_text(json.dumps(stats, indent=2))

    runs = []
    if finished:
        r, p = finished[0]
        runs.append({"label": f"{args.label}", "result": r, "code": p.read_text()})
    for label, p in [("Claude Opus 5.5", OPUS), ("Centerline baseline", BASELINE), ("Qwen3.6-35B untrained", QWEN_BASE)]:
        runs.append({"label": label, "result": run_lap(p), "code": p.read_text()})
    html = render_html(runs, ROOT / "out/showcase.html", "F1 lap-time RL — Qwen3.6-35B vs Opus vs baselines")
    print(html)
    if args.video:
        subprocess.run([sys.executable, str(ROOT / "record_video.py"), str(html), str(ROOT / "out/showcase.mp4"),
                        "--speed", "5", "--tail", "2.5"], check=True)


if __name__ == "__main__":
    main()
