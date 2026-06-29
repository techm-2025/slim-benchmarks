"""CLI runner: HTTP-over-SLIM full-mesh round-trip latency (cell 4).

Requires a SLIM node reachable at the endpoint in slim_bench/config.py:

    docker run --rm -d --name slim-node -p 46357:46357 \
      -v "$(pwd)/server-config.yaml:/config.yaml" \
      --entrypoint /slim ghcr.io/agntcy/slim:1.3.0 --config /config.yaml

Single run:
    python http_slim_mesh_benchmark.py --agents 20 --rounds 5 --payload-size 64 --concurrent

Sweep:
    python http_slim_mesh_benchmark.py --sweep --agents-list 5,10,20 \
      --payloads 64,512 --rounds 3 --output docs/evidence/http_slim_mesh_sweep.json
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

from slim_bench.config import SLIM_ENDPOINT, init_slim
from slim_bench.display import B, CY, MG, R, SEP2, log
from slim_bench.http_slim_mesh import (
    _payload,
    build_http_slim_mesh,
    run_full_http_slim_mesh,
    teardown_http_slim_mesh,
    warm_sessions,
)
from slim_bench.results import _summary_stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HTTP-over-SLIM full-mesh round-trip benchmark.")
    p.add_argument("--agents", type=int, default=20)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--payload-size", type=int, default=64)
    p.add_argument("--concurrent", action="store_true", help="Thread-based concurrent fanout.")
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--agents-list", type=str, default="5,10,20")
    p.add_argument("--payloads", type=str, default="64,512")
    p.add_argument("--output", type=str, default="")
    return p.parse_args()


def run_one(svc, conn_id, agents_n, payload_size, rounds, concurrent) -> dict:
    payload = _payload(payload_size)
    tag = f"hslim-{uuid.uuid4().hex[:8]}"
    agents = build_http_slim_mesh(svc, conn_id, agents_n, tag=tag)
    try:
        setup = warm_sessions(agents)
        result = run_full_http_slim_mesh(agents, payload, rounds, concurrent)
    finally:
        served = teardown_http_slim_mesh(agents)

    summary = result.summary()
    summary["metadata"]["requests_served_by_peers"] = served
    summary["session_setup"] = _summary_stats(setup)
    return summary


def print_row(s: dict) -> None:
    m = s["metadata"]
    log(MG, "RESULT",
        f"n={B}{m['agents']:>3}{R} pay={B}{m['payload_bytes']:>4}{R} {m['mode']:>10}"
        f"  trips={B}{s['count']:>5}{R} served={B}{m['requests_served_by_peers']:>5}{R}"
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
        for concurrent in (False, True):
            for n in agents_list:
                for pay in payloads:
                    log(CY, "SWEEP", f"n={n} payload={pay} concurrent={concurrent}")
                    results.append(run_one(svc, conn_id, n, pay, args.rounds, concurrent))
    else:
        results.append(run_one(svc, conn_id, args.agents, args.payload_size, args.rounds, args.concurrent))

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": SLIM_ENDPOINT,
        "transport": "http_over_slim",
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
