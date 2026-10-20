"""Container entry point: one F1 lap rollout for the platform-selected model."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from trajectory import Client  # noqa: E402

from f1env.rollout import rollout  # noqa: E402


def main() -> None:
    client = Client(max_retries=20)
    bundle = rollout(client, model="policy")
    print(json.dumps(bundle["summary"]), flush=True)


if __name__ == "__main__":
    main()
