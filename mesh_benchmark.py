"""CLI runner: real-SLIM full-mesh latency at a given agent count.

Validation harness for the full-mesh scale benchmark. Requires a SLIM node
reachable at the endpoint in slim_bench/config.py (default localhost:46357).

    docker run --rm -d --name slim-node -p 46357:46357 \
      -v "$(pwd)/server-config.yaml:/config.yaml" \
      --entrypoint /slim ghcr.io/agntcy/slim:1.3.0 --config /config.yaml

    python mesh_benchmark.py --agents 20 --rounds 1 --payload-size 64
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from slim_bench.config import SLIM_ENDPOINT, init_slim
from slim_bench.display import B, MG, R, SEP2, log
from slim_bench.mesh import build_mesh, run_full_mesh_round, teardown_mesh


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Real-SLIM full-mesh latency benchmark.")
    p.add_argument("--agents", type=int, default=20, help="Number of agents in the mesh.")
    p.add_argument("--rounds", type=int, default=1, help="Full-mesh rounds to run.")
    p.add_argument("--payload-size", type=int, default=64, help="Payload size in bytes.")
    p.add_argument("--output", type=str, default="", help="Optional JSON output path.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    payload = b"x" * args.payload_size

    svc = init_slim()
    conn_id = svc.get_connection_id(SLIM_ENDPOINT)
    if conn_id is None:
        raise SystemExit(f"Not connected to SLIM node at {SLIM_ENDPOINT}")

    agents = build_mesh(svc, conn_id, args.agents)
    try:
        result = run_full_mesh_round(agents, payload, args.rounds)
    finally:
        received = teardown_mesh(agents)

    summary = result.summary()
    summary["metadata"]["messages_received_by_peers"] = received

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": SLIM_ENDPOINT,
        "config": {
            "agents": args.agents,
            "rounds": args.rounds,
            "payload_size": args.payload_size,
        },
        "results": [summary],
    }

    print(SEP2)
    log(MG, "RESULT", f"agents={B}{args.agents}{R}  sent={B}{summary['count']}{R}  received={B}{received}{R}")
    log(MG, "RESULT", f"publish latency ms  mean={B}{summary['mean_ms']}{R}  p50={B}{summary['p50_ms']}{R}  p95={B}{summary['p95_ms']}{R}  max={B}{summary['max_ms']}{R}")
    print(SEP2)

    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
