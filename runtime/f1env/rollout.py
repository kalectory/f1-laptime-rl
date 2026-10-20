"""One rollout: prompt the model, extract its Policy code, race one lap, record the reward.

Shared by the container harness (model="policy", routed by the platform) and the local
runner (any catalog model, e.g. anthropic/claude-opus-5.5).
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import tempfile
import time
from pathlib import Path

import httpx2 as httpx

from f1env.prompt import SYSTEM_PROMPT, build_user_prompt, extract_code
from f1env.sim import MAX_LAP_TIME, W_PROGRESS, W_TIME, progress_score, run_lap, time_score

MAX_OUTPUT_TOKENS = 16384


def rollout(client, model: str, max_tokens: int = MAX_OUTPUT_TOKENS, temperature: float = 1.0) -> dict:
    tid = client.trajectories.create().tid
    t0 = time.time()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(max_tokens)},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            x_trajectory_id=tid,
        )
    except Exception:
        client.trajectories.complete(tid, termination_reason="ERROR")
        raise
    gen_seconds = time.time() - t0
    choice = response.choices[0]
    text = choice.message.content or ""
    usage = getattr(response, "usage", None)
    code = extract_code(text)

    if code is None:
        result = {
            "finished": False, "lap_time": None, "progress": 0.0, "reward": 0.0,
            "reason": "no_code", "max_speed_kph": 0.0, "gravel_time": 0.0, "sim_time": 0.0,
            "detail": f"no complete ```python block defining class Policy (finish_reason={choice.finish_reason})",
            "trace": [],
        }
    else:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "policy.py"
            path.write_text(code)
            result = run_lap(path)

    summary = {
        "tid": tid,
        "model": model,
        "lap_time": result["lap_time"],
        "finished": result["finished"],
        "reason": result["reason"],
        "detail": result.get("detail", "")[:1500],
        "progress": result["progress"],
        "reward": result["reward"],
        "max_speed_kph": result["max_speed_kph"],
        "gravel_time": result["gravel_time"],
        "finish_reason": choice.finish_reason,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        "generation_seconds": round(gen_seconds, 1),
    }
    bundle = {"summary": summary, "code": code, "response_text": text, "result": result}
    try:
        artifact_id = _upload_json(client, tid, bundle)
        client.trajectories.log_event(
            tid, event_id="f1-lap", name="f1_lap",
            payload={**summary, "artifact_id": artifact_id, "filename": "f1_lap.json.gz"},
        )
    except Exception as e:  # diagnostics must never change the reward
        print(f"artifact upload failed: {e!r}", flush=True)
    # Two components, averaged by the platform with equal weight. The time component is
    # always logged (0 on a DNF) so a near-miss DNF can never outscore a finished lap.
    client.trajectories.log_reward(tid, name="progress", value=progress_score(result),
                                   min_value=0.0, max_value=1.0, weight=W_PROGRESS)
    client.trajectories.log_reward(tid, name="lap_time_score", value=time_score(result),
                                   min_value=0.0, max_value=1.0, weight=W_TIME)
    if result["finished"]:
        client.trajectories.log_reward(tid, name="lap_time_s", value=float(result["lap_time"]),
                                       min_value=0.0, max_value=MAX_LAP_TIME, weight=0.0)
    completed = client.trajectories.complete(tid, termination_reason="ENV_DONE")
    if completed.status != "completed":
        raise RuntimeError(f"trajectory completion failed: {completed}")
    bundle["summary"]["status"] = completed.status
    return bundle


def _upload_json(client, tid: str, obj: dict) -> str:
    content = gzip.compress(json.dumps(obj, separators=(",", ":")).encode(), mtime=0)
    up = client.trajectories.artifacts.create_upload(
        tid, media_type="application/gzip", size_bytes=len(content),
        md5=base64.b64encode(hashlib.md5(content).digest()).decode(),
    )
    httpx.put(up.upload_url, content=content, headers=up.headers, timeout=120).raise_for_status()
    return client.trajectories.artifacts.complete_upload(tid, up.artifact_id).artifact_id
