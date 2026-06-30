"""CLI runner: A2A-over-SLIM full-mesh round-trip latency (cell 2).

Needs the agntcy A2A stack (.venv-a2a) and a slim:1.0.0 node started with the
Aether server config:

    docker run --rm -d --name slim-node -p 46357:46357 \
      -v "<pragitsm>/Aether/configs/server-config.yaml:/config.yaml" \
      ghcr.io/agntcy/slim:1.0.0 /slim --config /config.yaml

Agents always run as separate processes (true parallelism); --concurrent makes
each agent fan out to its peers via asyncio.gather instead of one at a time.

Single run:
    .venv-a2a/bin/python a2a_slim_mesh_benchmark.py --agents 5 --rounds 3 --payload-size 64 --concurrent

Sweep:
    .venv-a2a/bin/python a2a_slim_mesh_benchmark.py --sweep --agents-list 5,10,20 \
      --payloads 64 --rounds 3 --output docs/evidence/a2a_slim_mesh_sweep.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from slim_bench.a2a_slim_mesh import run_a2a_slim_mesh
from slim_bench.display import B, CY, MG, R, SEP2, log


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A2A-over-SLIM full-mesh round-trip benchmark.")
    p.add_argument("--agents", type=int, default=5)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--payload-size", type=int, default=64)
    p.add_argument("--concurrent", action="store_true", help="Concurrent per-agent fan-out.")
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--agents-list", type=str, default="5,10,20")
    p.add_argument("--payloads", type=str, default="64")
    p.add_argument("--output", type=str, default="")
    return p.parse_args()


def print_row(s: dict) -> None:
    m = s["metadata"]
    log(MG, "RESULT",
        f"n={B}{m['agents']:>3}{R} pay={B}{m['payload_bytes']:>4}{R} {m['mode']:>10}"
        f"  trips={B}{s['count']:>5}{R} done={B}{m['requests_completed']:>5}{R}"
        f"  mean={B}{s['mean_ms']:>6}{R} p95={B}{s['p95_ms']:>6}{R} p99={B}{s['p99_ms']:>6}{R}"
        f"  wall={B}{m['wall_ms']:>7}{R}ms")


def main() -> None:
    args = parse_args()
    results = []
    if args.sweep:
        agents_list = [int(x) for x in args.agents_list.split(",") if x.strip()]
        payloads = [int(x) for x in args.payloads.split(",") if x.strip()]
        for concurrent in (False, True):
            for n in agents_list:
                for pay in payloads:
                    log(CY, "SWEEP", f"n={n} payload={pay} concurrent={concurrent}")
                    results.append(run_a2a_slim_mesh(n, pay, args.rounds, concurrent).summary())
    else:
        results.append(
            run_a2a_slim_mesh(args.agents, args.payload_size, args.rounds, args.concurrent).summary()
        )

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "transport": "a2a_over_slim",
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
