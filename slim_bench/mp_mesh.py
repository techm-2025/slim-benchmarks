"""SLIM full-mesh with true process-level parallelism.

The concurrent mode in mesh.py uses threads under one GIL, so the Python side of
the sends is serialised even though the SLIM dataplane runs in Rust. This module
runs one OS process per agent: each process owns an independent SLIM runtime,
connects to the same node, subscribes its name, warms a session to every peer,
then fires its fan-out on a shared barrier. Concurrency is real parallelism
across cores.

This mirrors slim_bench/mp_http_mesh.py so the SLIM and HTTP parallel legs are
measured the same way. On a 12-core laptop, up to ~12 agents publish at the same
literal instant; beyond that the OS time-slices them.
"""

from __future__ import annotations

import datetime
import multiprocessing as mp
import time

import slim_bindings as slim

from .config import SECRET, SLIM_ENDPOINT, session_cfg
from .display import B, GR, R, YL, log
from .mesh import MeshAgent
from .results import MeshResult


def _quiet_init() -> slim.Service:
    """Initialise the SLIM runtime in this process without the banner output."""
    client_cfg = slim.new_insecure_client_config(SLIM_ENDPOINT)
    dataplane_cfg = slim.DataplaneConfig(servers=[], clients=[client_cfg])
    service_cfg = slim.new_service_config_with(node_id=None, group_name=None, dataplane=dataplane_cfg)
    runtime_cfg = slim.new_runtime_config_with(
        n_cores=1, thread_name="slim-rt", drain_timeout=datetime.timedelta(seconds=10)
    )
    slim.initialize_with_configs(runtime_cfg, slim.new_tracing_config(), [service_cfg])
    svc = slim.get_global_service()
    # Under N spawned processes the connection can take longer to come up than a
    # fixed sleep; poll until the node connection is actually established.
    for _ in range(100):
        if svc.get_connection_id(SLIM_ENDPOINT) is not None:
            break
        time.sleep(0.05)
    return svc


def _agent_proc(idx, n, payload, rounds, tag, ready, go, done, out_q) -> None:
    """One SLIM agent in its own process: own runtime, receiver, and sends."""
    svc = _quiet_init()
    conn_id = svc.get_connection_id(SLIM_ENDPOINT)
    if conn_id is None:
        out_q.put((idx, [], -1))  # signal a failed connection rather than hang
        return
    agent = MeshAgent(svc, conn_id, idx, SECRET, tag)
    agent.start_receiver()

    ready.wait()  # every app subscribed and listening before any session opens
    # Small settle so every peer is in listen_for_session before discovery.
    time.sleep(0.5)

    for j in range(n):
        if j != idx:
            peer = slim.Name("org", tag, f"agent-{j}")
            # With one connection per process the node won't forward to a peer
            # until this sender declares a route to that name over its own
            # connection. The single-connection thread model never needs this
            # because every app shares one connection the node already knows.
            agent.app.set_route(peer, conn_id)
            agent.sessions[j] = agent.app.create_session_and_wait(session_cfg(), peer)

    samples: list[float] = []
    go.wait()  # all senders released together
    for _ in range(rounds):
        for j in range(n):
            if j != idx:
                samples.append(agent.publish_to(j, payload))

    done.wait()  # no receiver stops while a slower peer is still publishing
    time.sleep(0.6)  # let in-flight messages land before counting
    received = agent.received
    out_q.put((idx, samples, received))
    agent.stop()


def run_parallel_mesh(n: int, payload: bytes, rounds: int, tag: str) -> MeshResult:
    """Process-per-agent concurrent full mesh over real SLIM."""
    ctx = mp.get_context("spawn")
    ready = ctx.Barrier(n)
    go = ctx.Barrier(n)
    done = ctx.Barrier(n)
    out_q: mp.Queue = ctx.Queue()

    expected = n * (n - 1) * rounds
    cores = mp.cpu_count()
    log(YL, "MP-SLIM",
        f"Process-per-agent [{B}parallel{R}]: {B}{n}{R} procs on {B}{cores}{R} cores, "
        f"{B}{n}x{n-1}{R} edges x {B}{rounds}{R} round(s) = {B}{expected}{R} messages")
    if n > cores:
        log(YL, "MP-SLIM",
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
        idx, samples, received = out_q.get()
        collected[idx] = (samples, received)
    for p in procs:
        p.join()
    wall = (time.perf_counter() - t0) * 1000.0

    all_samples: list[float] = []
    total_received = 0
    for idx in range(n):
        s, recv = collected[idx]
        all_samples.extend(s)
        total_received += recv

    log(GR, "MP-SLIM", f"done in {wall:.1f} ms — {len(all_samples)} sends, {total_received} received")

    return MeshResult(
        name="full_mesh_slim_unicast_parallel",
        samples=all_samples,
        metadata={
            "transport": "slim_unicast_point_to_point",
            "mode": "parallel",
            "agents": n,
            "rounds": rounds,
            "cpu_cores": cores,
            "directed_edges": n * (n - 1),
            "expected_messages": expected,
            "messages_received_by_peers": total_received,
            "payload_bytes": len(payload),
            "wall_ms": round(wall, 1),
        },
    )
