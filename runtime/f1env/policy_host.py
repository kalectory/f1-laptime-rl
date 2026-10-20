"""Child process that hosts untrusted policy code. Speaks JSON lines over stdin/stdout.

Protocol (one JSON object per line):
  parent -> {"init": {"track": ..., "car": ...}}       child -> {"ok": true} | {"error": "..."}
  parent -> {"obs": {...}}                              child -> {"a": [steer, throttle, brake]} | {"error": "..."}
The policy's own prints go to stderr, so they can't corrupt the protocol stream.
"""

import json
import os
import sys
import traceback


def main() -> None:
    proto_out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)  # anything the policy prints lands on stderr
    sys.stdout = sys.stderr
    path = sys.argv[1]

    def send(obj):
        proto_out.write(json.dumps(obj) + "\n")
        proto_out.flush()

    policy = None
    for line in sys.stdin:
        msg = json.loads(line)
        try:
            if "init" in msg:
                ns = {"__name__": "policy_module"}
                with open(path) as f:
                    code = compile(f.read(), "policy.py", "exec")
                exec(code, ns)
                if "Policy" not in ns:
                    raise RuntimeError("policy code does not define class Policy")
                policy = ns["Policy"](msg["init"]["track"], msg["init"]["car"])
                send({"ok": True})
            else:
                a = policy.act(msg["obs"])
                send({"a": [float(a[0]), float(a[1]), float(a[2])]})
        except BaseException:
            send({"error": traceback.format_exc(limit=6)[-2000:]})


if __name__ == "__main__":
    main()
