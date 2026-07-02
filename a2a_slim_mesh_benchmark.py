"""CLI runner: A2A-over-SLIM full-mesh round-trip latency benchmark.

Uses the public slima2a package (v0.6.0) and slim-bindings 1.4.1.
Requires SLIM node: ghcr.io/agntcy/slim:1.4.0

Start node:
    docker run --rm -d --name slim-node -p 46357:46357 \\
      -v "$PWD/server-config.yaml:/config.yaml" \\
      --entrypoint /slim ghcr.io/agntcy/slim:1.4.0 --config /config.yaml

Install:
    python3 -m venv .venv-a2a
    .venv-a2a/bin/pip install -e .

Single run:
    .venv-a2a/bin/python a2a_slim_mesh_benchmark.py --agents 5 --rounds 3 --payload-size 64

Concurrent mode:
    .venv-a2a/bin/python a2a_slim_mesh_benchmark.py --agents 5 --rounds 3 --concurrent

Sweep:
    .venv-a2a/bin/python a2a_slim_mesh_benchmark.py --sweep \\
      --agents-list 5,10,20 --payloads 64,512 --rounds 3 \\
      --output docs/evidence/a2a_slim_mesh_sweep.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from bench.a2a_slim_mesh import run_a2a_slim_mesh
from bench.display import B, CY, MG, R, SEP2, log


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A2A-over-SLIM full-mesh round-trip benchmark.")
    p.add_argument("--agents",       type=int,  default=5,        help="Number of agents (default: 5)")
    p.add_argument("--rounds",       type=int,  default=1,        help="Rounds per agent pair (default: 1)")
    p.add_argument("--payload-size", type=int,  default=64,       help="Payload bytes (default: 64)")
    p.add_argument("--concurrent",   action="store_true",         help="Concurrent per-agent fan-out")
    p.add_argument("--sweep",        action="store_true",         help="Run a parameter sweep")
    p.add_argument("--agents-list",  type=str,  default="5,10,20", help="Comma-separated agent counts for sweep")
    p.add_argument("--payloads",     type=str,  default="64",     help="Comma-separated payload sizes for sweep")
    p.add_argument("--output",       type=str,  default="",       help="Write JSON report to this file")
    return p.parse_args()


def _print_row(s: dict) -> None:
    m = s["metadata"]
    log(MG, "RESULT",
        f"n={B}{m['agents']:>3}{R}  pay={B}{m['payload_bytes']:>4}B{R}  {m['mode']:>10}"
        f"  trips={B}{s['count']:>5}{R}  done={B}{m['requests_completed']:>5}{R}"
        f"  mean={B}{s['mean_ms']:>7.2f}{R}ms"
        f"  p95={B}{s['p95_ms']:>7.2f}{R}ms"
        f"  p99={B}{s['p99_ms']:>7.2f}{R}ms"
        f"  wall={B}{m['wall_ms']:>8.0f}{R}ms"
        f"  delivery={B}{m['delivery_pct']:.1f}%{R}")


def main() -> None:
    args = parse_args()
    results = []

    if args.sweep:
        agents_list = [int(x) for x in args.agents_list.split(",") if x.strip()]
        payloads = [int(x) for x in args.payloads.split(",") if x.strip()]
        for concurrent in (False, True):
            for n in agents_list:
                for pay in payloads:
                    log(CY, "SWEEP",
                        f"n={n}  payload={pay}B  concurrent={concurrent}")
                    results.append(
                        run_a2a_slim_mesh(n, pay, args.rounds, concurrent).summary()
                    )
    else:
        results.append(
            run_a2a_slim_mesh(
                args.agents, args.payload_size, args.rounds, args.concurrent
            ).summary()
        )

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "transport": "a2a_over_slim",
        "package": "slima2a==0.6.0",
        "slim_bindings": "1.4.1",
        "slim_node": "ghcr.io/agntcy/slim:1.4.0",
        "rounds": args.rounds,
        "results": results,
    }

    print(SEP2)
    for s in results:
        _print_row(s)
    print(SEP2)

    text = json.dumps(report, indent=2)
    if args.output:
        import os
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        log(MG, "RESULT", f"wrote {B}{args.output}{R}")
    else:
        print(text)


if __name__ == "__main__":
    main()
