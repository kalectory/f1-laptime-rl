"""Overlay several platform evals (plus optional local policies) in one replay.

  python compare.py --eval "Opus 5.5=evr_..." --eval "Qwen3.6-35B-A3B=evr_..." \
      --policy "Baseline (centerline)=policies/baseline_centerline.py" --out out/compare.html

Run `python f1.py replay --eval-id ...` first; this reads its cached responses in out/eval_<id>/.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "runtime"))

from f1env.prompt import extract_code  # noqa: E402
from f1env.render import render_html  # noqa: E402
from f1env.sim import run_lap  # noqa: E402

_NO_CODE = {"finished": False, "lap_time": None, "progress": 0.0, "reward": 0.0, "reason": "no_code",
            "max_speed_kph": 0.0, "gravel_time": 0.0, "detail": "no complete python block", "trace": []}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="append", default=[], help="LABEL=EVAL_RUN_ID")
    ap.add_argument("--policy", action="append", default=[], help="LABEL=path/to/policy.py")
    ap.add_argument("--out", default="out/compare.html")
    ap.add_argument("--title", default="F1 Lap Replay — model comparison")
    args = ap.parse_args()

    runs = []
    for spec in args.eval:
        label, eid = spec.split("=", 1)
        group = []
        for resp in sorted((ROOT / "out" / f"eval_{eid}").glob("*_response.md")):
            text = resp.read_text()
            code = extract_code(text)
            if code is None:
                result = dict(_NO_CODE)
            else:
                path = resp.with_name(resp.name.replace("_response.md", "_policy.py"))
                path.write_text(code)
                result = run_lap(path)
            group.append({"result": result, "code": code, "response": text})
        group.sort(key=lambda r: r["result"]["lap_time"] or 1e9)
        for i, r in enumerate(group, 1):
            runs.append({"label": f"{label} #{i}", **r})
    for spec in args.policy:
        label, path = spec.split("=", 1)
        runs.append({"label": label, "result": run_lap(path), "code": Path(path).read_text()})
    for r in runs:
        res = r["result"]
        print(f"{r['label']:32s} {f'{res['lap_time']:.3f}s' if res['finished'] else 'DNF · ' + res['reason']}")
    print(render_html(runs, ROOT / args.out, args.title))


if __name__ == "__main__":
    main()
