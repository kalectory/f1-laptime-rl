"""Diagnose a training run: re-simulate a sample of its rollouts per policy step.

  python analyze_training.py TRAINING_RUN_ID [--per-step 40]

Writes out/train_<id>/summary.jsonl and prints, per step: outcome mix, where cars crash,
and response length. The sim is deterministic, so re-running the code reproduces the
reward the trainer saw.
"""

import argparse
import concurrent.futures as cf
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "runtime"))

from f1env.prompt import extract_code  # noqa: E402
from f1env.sim import run_lap  # noqa: E402

# centerline progress (m) -> named section, for crash locations
SECTIONS = [(0, 900, "main straight"), (900, 1300, "T1 hairpin"), (1300, 1880, "esses"),
            (1880, 2200, "T6-T7 left"), (2200, 2680, "back straight"), (2680, 2960, "chicane"),
            (2960, 3700, "T10 sweeper"), (3700, 4900, "top straight"), (4900, 5400, "final lefts")]


def section(s):
    return next((n for a, b, n in SECTIONS if a <= s < b), "?")


def fetch(client, tid):
    steps = list(client.trajectories.steps.list(tid))
    msgs = [m for st in steps for m in st.model_dump()["messages"] if m["role"] == "assistant"]
    m = msgs[-1] if msgs else {}
    return m.get("content") or "", m.get("completion_tokens"), m.get("finish_reason")


def simulate(args):
    tid, step, text, toks, fin, outdir = args
    code = extract_code(text)
    row = {"tid": tid, "step": step, "tokens": toks, "finish_reason": fin}
    if code is None:
        row.update(reason="no_code", progress=0.0, reward=0.0, lap_time=None, crash_s=None, err=None)
        return row
    p = outdir / f"{tid}.py"
    p.write_text(code)
    r = run_lap(p, record_trace=False)
    err = None
    if r["reason"] == "policy_error":
        lines = [ln for ln in r["detail"].strip().splitlines() if ln.strip()]
        err = next((ln.strip() for ln in reversed(lines) if "Error" in ln), lines[-1] if lines else "")[:100]
    crash_s = r["progress"] * r["track_length"] if r["reason"] in ("crash", "stalled", "time_limit") else None
    row.update(reason=r["reason"], progress=r["progress"], reward=r["reward"], lap_time=r["lap_time"],
               crash_s=crash_s, err=err, max_kph=r["max_speed_kph"])
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--per-step", type=int, default=40)
    args = ap.parse_args()
    from trajectory import Client

    client = Client(max_retries=10)
    outdir = ROOT / "out" / f"train_{args.run_id}"
    (outdir / "code").mkdir(parents=True, exist_ok=True)
    trajs = [t.model_dump() for t in client.trajectories.list(training_run_id=args.run_id, limit=200)]
    by_step = defaultdict(list)
    for t in trajs:
        by_step[t["policy_step"]].append(t["trajectory_id"])
    random.seed(0)
    sample = [(s, tid) for s, tids in sorted(by_step.items()) for tid in random.sample(tids, min(args.per_step, len(tids)))]
    with cf.ThreadPoolExecutor(16) as ex:
        fetched = list(ex.map(lambda st: (st[1], st[0], *fetch(client, st[1])), sample))
    with cf.ProcessPoolExecutor() as ex:
        rows = list(ex.map(simulate, [(*f, outdir / "code") for f in fetched]))
    with open(outdir / "summary.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    for step in sorted(by_step):
        rs = [r for r in rows if r["step"] == step]
        n = len(rs)
        oc = Counter(r["reason"] for r in rs)
        crashes = Counter(section(r["crash_s"]) for r in rs if r["crash_s"] is not None)
        toks = [r["tokens"] for r in rs if r["tokens"]]
        trunc = sum(1 for r in rs if (r["tokens"] or 0) >= 16384)
        mean_r = sum(r["reward"] for r in rs) / max(n, 1)
        laps = [r["lap_time"] for r in rs if r["lap_time"]]
        print(f"step {step} (n={n}): mean_raw={mean_r:.4f}  finished={len(laps)}{f' best={min(laps):.1f}s' if laps else ''}  "
              f"truncated={trunc}  avg_tok={sum(toks) / max(len(toks), 1):.0f}")
        print(f"   outcomes: {dict(oc)}")
        if crashes:
            print(f"   DNF location: {dict(crashes.most_common())}")
    errs = Counter(r["err"] for r in rows if r["err"])
    print("top policy errors:", errs.most_common(6))


if __name__ == "__main__":
    main()
