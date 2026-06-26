"""CLI runner: HTTP full-mesh latency with no SLIM (the mesh-config baseline).

Cell 3 of the four-cell comparison. Needs no SLIM node and no Docker — it runs
plain HTTP servers on loopback. Mirrors mesh_benchmark.py so the two emit the
same result shape.

Single run:
    python http_mesh_benchmark.py --agents 20 --rounds 5 --payload-size 64 --concurrent

Sweep (agent counts x payload sizes, both modes):
    python http_mesh_benchmark.py --sweep --agents-list 10,20,40 \
      --payloads 64,512,4096 --rounds 5 --output docs/evidence/http_mesh_sweep.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from slim_bench.display import B, CY, MG, R, SEP2, log
from slim_bench.http_mesh import (
    build_http_mesh,
    run_full_http_mesh,
    teardown_http_mesh,
    warm_connections,
)
from slim_bench.mp_http_mesh import run_parallel_http_mesh
from slim_bench.results import _summary_stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HTTP full-mesh latency benchmark (no SLIM).")
    p.add_argument("--agents", type=int, default=20, help="Agents (single-run mode).")
    p.add_argument("--rounds", type=int, default=1, help="Full-mesh rounds per config.")
    p.add_argument("--payload-size", type=int, default=64, help="Payload bytes (single-run).")
    p.add_argument("--concurrent", action="store_true", help="Thread-based concurrent fanout (single-run).")
    p.add_argument("--parallel", action="store_true",
                   help="True process-per-agent parallel fanout (single-run); overrides --concurrent.")
    p.add_argument("--sweep", action="store_true", help="Run an agent x payload x mode sweep.")
    p.add_argument("--agents-list", type=str, default="10,20,40", help="Sweep agent counts (csv).")
    p.add_argument("--payloads", type=str, default="64,512,4096", help="Sweep payload sizes (csv).")
    p.add_argument("--output", type=str, default="", help="Optional JSON output path.")
    return p.parse_args()


def run_one(agents_n, payload_size, rounds, mode) -> dict:
    """mode is one of 'sequential', 'concurrent' (threads), 'parallel' (processes)."""
    payload = b"x" * payload_size
    if mode == "parallel":
        # Process-per-agent harness manages its own servers/connections.
        result = run_parallel_http_mesh(agents_n, payload, rounds)
        return result.summary()

    agents = build_http_mesh(agents_n)
    try:
        setup = warm_connections(agents)
        result = run_full_http_mesh(agents, payload, rounds, concurrent=(mode == "concurrent"))
    finally:
        received = teardown_http_mesh(agents)

    summary = result.summary()
    summary["metadata"]["messages_received_by_peers"] = received
    summary["session_setup"] = _summary_stats(setup)
    return summary


def print_row(s: dict) -> None:
    m = s["metadata"]
    wall = m.get("round_wall_mean_ms", m.get("wall_ms", 0.0))
    log(MG, "RESULT",
        f"n={B}{m['agents']:>3}{R} pay={B}{m['payload_bytes']:>4}{R} {m['mode']:>10}"
        f"  sent={B}{s['count']:>5}{R} recv={B}{m['messages_received_by_peers']:>5}{R}"
        f"  mean={B}{s['mean_ms']:>6}{R} p95={B}{s['p95_ms']:>6}{R} p99={B}{s['p99_ms']:>6}{R}"
        f"  wall={B}{wall:>7}{R}ms")


def main() -> None:
    args = parse_args()

    results = []
    if args.sweep:
        agents_list = [int(x) for x in args.agents_list.split(",") if x.strip()]
        payloads = [int(x) for x in args.payloads.split(",") if x.strip()]
        # parallel (true process-per-agent) is the credible concurrency leg; the
        # thread-based 'concurrent' leg is kept for reference / GIL comparison.
        modes = ["sequential", "concurrent", "parallel"] if args.parallel else ["sequential", "concurrent"]
        for mode in modes:
            for n in agents_list:
                for pay in payloads:
                    log(CY, "SWEEP", f"n={n} payload={pay} mode={mode}")
                    results.append(run_one(n, pay, args.rounds, mode))
    else:
        mode = "parallel" if args.parallel else ("concurrent" if args.concurrent else "sequential")
        results.append(run_one(args.agents, args.payload_size, args.rounds, mode))

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "transport": "http_no_slim",
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
