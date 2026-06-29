"""HTTP-over-SLIM full-mesh with true process-level parallelism (cell 4).

Mirrors mp_mesh.py but carries an HTTP-style request/response round trip over
each SLIM session instead of a one-way publish. One process per agent: each owns
its SLIM runtime and connection, serves inbound requests, declares routes to its
peers, and on a shared barrier sends a request to every peer and waits for the
reply. Concurrency is real parallelism across cores; true simultaneity caps at
the core count, beyond which the OS time-slices.
"""

from __future__ import annotations

import multiprocessing as mp
import time

import slim_bindings as slim

from .config import SECRET, SLIM_ENDPOINT, session_cfg
from .display import B, GR, R, YL, log
from .http_slim_mesh import HttpSlimAgent
from .mp_mesh import _quiet_init
from .results import MeshResult


def _agent_proc(idx, n, payload, rounds, tag, ready, go, done, out_q) -> None:
    svc = _quiet_init()
    conn_id = svc.get_connection_id(SLIM_ENDPOINT)
    if conn_id is None:
        out_q.put((idx, [], -1))
        return
    agent = HttpSlimAgent(svc, conn_id, idx, SECRET, tag)
    agent.start_server()

    ready.wait()
    time.sleep(0.5)  # let every peer reach listen_for_session before discovery

    for j in range(n):
        if j != idx:
            peer = slim.Name("org", tag, f"agent-{j}")
            agent.app.set_route(peer, conn_id)
            agent.sessions[j] = agent.app.create_session_and_wait(session_cfg(), peer)

    samples: list[float] = []
    go.wait()
    for _ in range(rounds):
        for j in range(n):
            if j != idx:
                samples.append(agent.request_to(j, payload))

    done.wait()
    time.sleep(0.6)
    served = agent.served
    out_q.put((idx, samples, served))
    agent.stop()


def run_parallel_http_slim_mesh(n: int, payload: bytes, rounds: int, tag: str) -> MeshResult:
    ctx = mp.get_context("spawn")
    ready = ctx.Barrier(n)
    go = ctx.Barrier(n)
    done = ctx.Barrier(n)
    out_q: mp.Queue = ctx.Queue()

    expected = n * (n - 1) * rounds
    cores = mp.cpu_count()
    log(YL, "MP-HSLIM",
        f"Process-per-agent [{B}parallel{R}]: {B}{n}{R} procs on {B}{cores}{R} cores, "
        f"{B}{n}x{n-1}{R} edges x {B}{rounds}{R} round(s) = {B}{expected}{R} round trips")
    if n > cores:
        log(YL, "MP-HSLIM",
            f"note: {n} agents > {cores} cores — beyond {cores} the OS time-slices, "
            f"so not all sends are truly simultaneous")

    t0 = time.perf_counter()
    procs = [
        ctx.Process(target=_agent_proc, args=(i, n, payload, rounds, tag, ready, go, done, out_q))
        for i in range(n)
    ]
    for p in procs:
        p.start()

    collected: dict[int, tuple[list[float], int]] = {}
    while len(collected) < n:
        idx, samples, served = out_q.get()
        collected[idx] = (samples, served)
    for p in procs:
        p.join()
    wall = (time.perf_counter() - t0) * 1000.0

    all_samples: list[float] = []
    total_served = 0
    for idx in range(n):
        s, served = collected[idx]
        all_samples.extend(s)
        total_served += served

    log(GR, "MP-HSLIM", f"done in {wall:.1f} ms — {len(all_samples)} round trips, {total_served} served")

    return MeshResult(
        name="full_mesh_http_over_slim_parallel",
        samples=all_samples,
        metadata={
            "transport": "http_over_slim",
            "mode": "parallel",
            "agents": n,
            "rounds": rounds,
            "cpu_cores": cores,
            "directed_edges": n * (n - 1),
            "expected_messages": expected,
            "requests_served_by_peers": total_served,
            "payload_bytes": len(payload),
            "wall_ms": round(wall, 1),
        },
    )
