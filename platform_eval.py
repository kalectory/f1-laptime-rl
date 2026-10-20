"""Register the F1 lap-time benchmark and run evaluations on the Trajectory platform.

  python platform_eval.py push                       # register benchmark + build image
  python platform_eval.py eval --model Qwen/Qwen3.6-35B-A3B --model anthropic/claude-opus-5.5
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from trajectory import BenchmarkSpec, Client, TaskSpec
from trajectory.lib import DockerfileBuild, push, wait_for_benchmark_images

ROOT = Path(__file__).parent
STATE = ROOT / "out" / "platform.json"
AGENT = "f1-laptime"
BENCH = "f1-laptime-single-track"
RUN_COMMAND = "python -u /opt/f1/harness.py"


def _state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _save(**kw) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({**_state(), **kw}, indent=2))


def cmd_push(args) -> None:
    client = Client(max_retries=10)
    if AGENT not in {a.name for a in client.agents.list()}:
        client.agents.create(name=AGENT, description="Write policy code for a simulated F1 car; reward = 100 / lap time on one fixed track")
    # One track, identical start state: the train and test tasks are the same task.
    spec = BenchmarkSpec(
        name=BENCH,
        family="f1-laptime",
        description="Write a Python driving policy for a simulated F1 car; reward = 100 / lap time (one fixed circuit, deterministic physics).",
        runtime=DockerfileBuild("runtime/Dockerfile"),
        tasks=[
            TaskSpec(name=f"f1-lap/{split}_0000", split=split, run_command=RUN_COMMAND, tags=["f1-laptime"])
            for split in ("train", "test")
        ],
    )
    result = push(client, spec, agent_name=AGENT, root=ROOT)
    print(f"bench_id={result.bench_id}", flush=True)
    _save(bench_id=result.bench_id)
    images = wait_for_benchmark_images(client, result.bench_id, timeout_seconds=45 * 60)
    print(f"images ready: {[getattr(i, 'status', i) for i in images]}")


def cmd_eval(args) -> None:
    client = Client(max_retries=10)
    bench_id = args.bench_id or _state()["bench_id"]
    ids = {}
    for model in args.model:
        opts = {
            "evaluation_samples_per_task": args.n,
            "evaluation_max_active_rollouts": args.n,
            "max_output_tokens_per_step": 16384,
            "max_turns_per_trajectory": 1,
            "execution_timeout_seconds": 1800,
            "evaluation_collection_timeout_seconds": 3600,
        }
        tag = f" · ckpt {args.checkpoint[-6:]}" if args.checkpoint else ""
        ev = client.evals.create(bench_id=bench_id, base_model_slug=model, parent_checkpoint_id=args.checkpoint,
                                 display_name=f"F1 lap time · {model}{tag} · {args.n} rollouts", options=opts)
        ids[model] = ev.eval_run_id
        print(f"{model}: eval_run_id={ev.eval_run_id}", flush=True)
    _save(evals={**_state().get("evals", {}), **ids})
    pending = dict(ids)
    while pending:
        time.sleep(20)
        for model, eid in list(pending.items()):
            p = client.evals.runs.progress(eid)
            print(f"{model}: {p.status} {p.terminal_rollouts}/{p.total_rollouts}", flush=True)
            if p.status in {"completed", "failed", "cancelled"}:
                pending.pop(model)
                if p.status != "completed":
                    print(f"  failure: {getattr(p, 'failure', None)}")
    for model, eid in ids.items():
        r = client.evals.runs.retrieve(eid)
        print(f"{model}: reward_mean={r.reward_mean}  eval_run_id={eid}")


def cmd_train(args) -> None:
    client = Client(max_retries=10)
    bench_id = args.bench_id or _state()["bench_id"]
    opts = {
        "num_steps": args.steps,
        "train_batch_size": args.batch,
        "samples_per_instance": args.group,
        "lr_warmup_steps": 1,
        "lr_hold_steps": args.hold if args.hold is not None else args.steps,
        "max_output_tokens_per_step": 16384,
        "max_turns_per_trajectory": 1,
        "train_on_truncation": True,  # 16k-token rambling with no code should be penalised, not skipped
        "execution_timeout_seconds": 1800,
        "batch_collection_idle_timeout_seconds": 5400,
        # held-out evals during training: 10 rollouts of the test task instead of the default 1
        "evaluation_samples_per_task": 10,
        "evaluation_max_active_rollouts": 10,
    }
    run = client.training.create(bench_id=bench_id, base_model_slug=args.model, options=opts,
                                 parent_checkpoint_id=args.checkpoint,
                                 display_name=f"F1 lap time · {args.model} · {args.steps} steps")
    rid = run.training_run_id
    print(f"training_run_id={rid}", flush=True)
    _save(training_runs=[*_state().get("training_runs", []), rid])
    while True:
        r = client.training.runs.retrieve(rid)
        p = client.training.runs.progress(rid)
        print(f"status={r.status} steps={p.completed_steps}/{p.total_steps or '?'}", flush=True)
        if str(r.status) in {"succeeded", "failed", "cancelled"}:
            if str(r.status) != "succeeded":
                print(f"failure: {getattr(r, 'failure', None)}", flush=True)
            break
        time.sleep(60)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("push").set_defaults(fn=cmd_push)
    e = sub.add_parser("eval")
    e.add_argument("--model", action="append", required=True)
    e.add_argument("-n", type=int, default=3)
    e.add_argument("--bench-id")
    e.add_argument("--checkpoint", help="parent_checkpoint_id from a training run")
    e.set_defaults(fn=cmd_eval)
    t = sub.add_parser("train")
    t.add_argument("--model", default="Qwen/Qwen3.6-35B-A3B")
    t.add_argument("--steps", type=int, default=10)
    t.add_argument("--batch", type=int, default=4)
    t.add_argument("--group", type=int, default=16)
    t.add_argument("--bench-id")
    t.add_argument("--checkpoint", help="resume training from this parent_checkpoint_id")
    t.add_argument("--hold", type=int, help="steps at full LR before cosine decay (default: all steps)")
    t.set_defaults(fn=cmd_train)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
