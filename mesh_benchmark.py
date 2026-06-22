"""CLI runner: real-SLIM full-mesh latency, single config or sweep.

Requires a SLIM node reachable at the endpoint in slim_bench/config.py
(default localhost:46357):

    docker run --rm -d --name slim-node -p 46357:46357 \
      -v "$(pwd)/server-config.yaml:/config.yaml" \
      --entrypoint /slim ghcr.io/agntcy/slim:1.3.0 --config /config.yaml

Single run:
    python mesh_benchmark.py --agents 20 --rounds 5 --payload-size 64 --concurrent

Sweep (agent counts x payload sizes, both modes):
    python mesh_benchmark.py --sweep --agents-list 10,20,40 \
      --payloads 64,512,4096 --rounds 5 --output docs/evidence/sweep.json
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

from slim_bench.config import SLIM_ENDPOINT, init_slim
from slim_bench.display import B, CY, MG, R, SEP2, log
from slim_bench.mesh import (
    build_mesh,
    run_full_mesh,
    teardown_mesh,
    warm_sessions,
    _summary_stats,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Real-SLIM full-mesh latency benchmark.")
    p.add_argument("--agents", type=int, default=20, help="Agents (single-run mode).")
    p.add_argument("--rounds", type=int, default=1, help="Full-mesh rounds per config.")
    p.add_argument("--payload-size", type=int, default=64, help="Payload bytes (single-run).")
    p.add_argument("--concurrent", action="store_true", help="Concurrent fanout (single-run).")
    p.add_argument("--sweep", action="store_true", help="Run an agent x payload x mode sweep.")
    p.add_argument("--agents-list", type=str, default="10,20,40", help="Sweep agent counts (csv).")
    p.add_argument("--payloads", type=str, default="64,512,4096", help="Sweep payload sizes (csv).")
    p.add_argument("--output", type=str, default="", help="Optional JSON output path.")
    return p.parse_args()


def run_one(svc, conn_id, agents_n, payload_size, rounds, concurrent) -> dict:
    payload = b"x" * payload_size
    # Unique namespace per run so repeated configs on one service never collide
    # with stale subscriptions/sessions from a previous config.
    tag = f"mesh-{uuid.uuid4().hex[:8]}"
    agents = build_mesh(svc, conn_id, agents_n, tag=tag)
    try:
        setup = warm_sessions(agents)
        result = run_full_mesh(agents, payload, rounds, concurrent)
    finally:
        received = teardown_mesh(agents)

    summary = result.summary()
    summary["metadata"]["messages_received_by_peers"] = received
    summary["session_setup"] = _summary_stats(setup)
    return summary


def print_row(s: dict) -> None:
    m = s["metadata"]
    log(MG, "RESULT",
        f"n={B}{m['agents']:>3}{R} pay={B}{m['payload_bytes']:>4}{R} {m['mode']:>10}"
        f"  sent={B}{s['count']:>5}{R} recv={B}{m['messages_received_by_peers']:>5}{R}"
        f"  mean={B}{s['mean_ms']:>6}{R} p95={B}{s['p95_ms']:>6}{R} p99={B}{s['p99_ms']:>6}{R}"
        f"  round={B}{m['round_wall_mean_ms']:>7}{R}ms")


def main() -> None:
    args = parse_args()

    svc = init_slim()
    conn_id = svc.get_connection_id(SLIM_ENDPOINT)
    if conn_id is None:
        raise SystemExit(f"Not connected to SLIM node at {SLIM_ENDPOINT}")

    results = []
    if args.sweep:
        agents_list = [int(x) for x in args.agents_list.split(",") if x.strip()]
        payloads = [int(x) for x in args.payloads.split(",") if x.strip()]
        for mode_concurrent in (False, True):
            for n in agents_list:
                for pay in payloads:
                    log(CY, "SWEEP", f"n={n} payload={pay} concurrent={mode_concurrent}")
                    results.append(run_one(svc, conn_id, n, pay, args.rounds, mode_concurrent))
    else:
        results.append(
            run_one(svc, conn_id, args.agents, args.payload_size, args.rounds, args.concurrent)
        )

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": SLIM_ENDPOINT,
        "rounds": args.rounds,
        "results": results,
    }

    print(SEP2)
    for s in results:
        print_row(s)
    print(SEP2)

    text = json.dumps(report, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        log(MG, "RESULT", f"wrote {B}{args.output}{R}")
    else:
        print(text)


if __name__ == "__main__":
    main()
