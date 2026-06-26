"""Full-mesh SLIM benchmark over a real SLIM node.

Builds N real SLIM apps (agents) on the live broker and runs full-mesh rounds:
every agent holds a POINT_TO_POINT session to every other agent and publishes
one message per round. Two execution modes:

* sequential — one publish in flight at a time. Clean per-message latency.
* concurrent — every agent fans out to all peers at once (thread per source).
  Measures behaviour under congestion, which is the property that matters for
  SLIM at scale.

Sessions are established once in a warm phase so per-round timings measure the
publish path, not session setup (setup is reported separately).

Unlike the in-memory `InMemorySlimBus` in A2A-MAS-no-SLIM/demo_benchmark.py,
this exercises the actual SLIM dataplane through `slim-bindings`.
"""

from __future__ import annotations

import datetime
import statistics
import threading
import time

import slim_bindings as slim

from .config import SECRET, session_cfg
from .display import B, CY, GR, R, RD, YL, log
from .results import MeshResult, _summary_stats

# Short poll timeout for receiver loops so they can notice the stop flag.
RECV_POLL = datetime.timedelta(seconds=2)


class MeshAgent:
    """One SLIM app that both receives (any peer) and sends (to any peer)."""

    def __init__(self, svc: slim.Service, conn_id: int, idx: int, secret: str, tag: str = "mesh") -> None:
        self.idx = idx
        self.name = slim.Name("org", tag, f"agent-{idx}")
        self.app = svc.create_app_with_secret(self.name, secret)
        self.app.subscribe(self.name, conn_id)

        self.received = 0
        self.sessions: dict[int, slim.Session] = {}  # dest idx -> open session
        self._stop = threading.Event()
        self._drainers: list[threading.Thread] = []
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)

    def start_receiver(self) -> None:
        self._recv_thread.start()

    def _recv_loop(self) -> None:
        # Accept inbound sessions from peers until stopped; each session gets
        # its own drainer so a slow peer never blocks the others.
        while not self._stop.is_set():
            try:
                session = self.app.listen_for_session(RECV_POLL)
            except Exception:
                continue  # timeout with no inbound session — re-poll
            t = threading.Thread(target=self._drain, args=(session,), daemon=True)
            t.start()
            self._drainers.append(t)

    def _drain(self, session: slim.Session) -> None:
        while not self._stop.is_set():
            try:
                session.get_message(RECV_POLL)
            except Exception:
                break  # session closed or idle past the poll window
            self.received += 1

    def open_session_to(self, dest: "MeshAgent") -> float:
        """Open and cache a session to dest. Returns session-setup ms."""
        t0 = time.perf_counter()
        self.sessions[dest.idx] = self.app.create_session_and_wait(session_cfg(), dest.name)
        return (time.perf_counter() - t0) * 1000.0

    def publish_to(self, dest_idx: int, payload: bytes) -> float:
        """Publish on the cached session to dest_idx. Returns publish ms."""
        session = self.sessions[dest_idx]
        t0 = time.perf_counter()
        session.publish_and_wait(payload, None, None)
        return (time.perf_counter() - t0) * 1000.0

    def stop(self) -> None:
        self._stop.set()


def build_mesh(svc: slim.Service, conn_id: int, n: int, secret: str = SECRET, tag: str = "mesh") -> list[MeshAgent]:
    log(CY, "MESH", f"Building {B}{n}{R} agents on conn_id={B}{conn_id}{R} (tag={tag})")
    agents = [MeshAgent(svc, conn_id, i, secret, tag) for i in range(n)]
    for a in agents:
        a.start_receiver()
    # Give every receiver a moment to reach listen_for_session before any send.
    time.sleep(0.5)
    log(GR, "MESH", f"All {B}{n}{R} agents subscribed and listening")
    return agents


def warm_sessions(agents: list[MeshAgent]) -> list[float]:
    """Open every directed session once. Returns per-session setup latencies."""
    n = len(agents)
    setup: list[float] = []
    for src in agents:
        for dst in agents:
            if src.idx != dst.idx:
                setup.append(src.open_session_to(dst))
    log(GR, "MESH", f"Warmed {B}{len(setup)}{R} sessions (setup mean {statistics.mean(setup):.2f} ms)")
    return setup


def _run_sequential(agents: list[MeshAgent], payload: bytes) -> list[float]:
    samples: list[float] = []
    for src in agents:
        for dst in agents:
            if src.idx != dst.idx:
                try:
                    samples.append(src.publish_to(dst.idx, payload))
                except Exception as exc:
                    log(RD, "MESH", f"send {src.idx}->{dst.idx} failed: {exc}")
    return samples


def _run_concurrent(agents: list[MeshAgent], payload: bytes) -> list[float]:
    # Each source agent fans out to all peers on its own thread; all sources
    # fire together so the broker sees simultaneous load.
    per_thread: list[list[float]] = [[] for _ in agents]
    barrier = threading.Barrier(len(agents))

    def worker(src: MeshAgent, sink: list[float]) -> None:
        barrier.wait()  # release all sources at the same instant
        for dst in agents:
            if src.idx != dst.idx:
                try:
                    sink.append(src.publish_to(dst.idx, payload))
                except Exception as exc:
                    log(RD, "MESH", f"send {src.idx}->{dst.idx} failed: {exc}")

    threads = [
        threading.Thread(target=worker, args=(src, per_thread[i]), daemon=True)
        for i, src in enumerate(agents)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    samples: list[float] = []
    for s in per_thread:
        samples.extend(s)
    return samples


def run_full_mesh(
    agents: list[MeshAgent],
    payload: bytes,
    rounds: int,
    concurrent: bool,
) -> MeshResult:
    n = len(agents)
    mode = "concurrent" if concurrent else "sequential"
    expected = n * (n - 1) * rounds
    log(YL, "MESH",
        f"Full-mesh [{B}{mode}{R}]: {B}{n}x{n-1}{R} edges x {B}{rounds}{R} round(s) = {B}{expected}{R} messages")

    samples: list[float] = []
    round_wall: list[float] = []
    runner = _run_concurrent if concurrent else _run_sequential
    for r in range(rounds):
        t0 = time.perf_counter()
        samples.extend(runner(agents, payload))
        round_wall.append((time.perf_counter() - t0) * 1000.0)
        log(CY, "MESH", f"round {r + 1}/{rounds} done in {round_wall[-1]:.1f} ms — {len(samples)} sends total")

    return MeshResult(
        name=f"full_mesh_slim_unicast_{mode}",
        samples=samples,
        metadata={
            "transport": "slim_unicast_point_to_point",
            "mode": mode,
            "agents": n,
            "rounds": rounds,
            "directed_edges": n * (n - 1),
            "expected_messages": expected,
            "payload_bytes": len(payload),
            "round_wall_ms": [round(x, 1) for x in round_wall],
            "round_wall_mean_ms": round(statistics.mean(round_wall), 1) if round_wall else 0.0,
        },
    )


def teardown_mesh(agents: list[MeshAgent], drain_wait: float = 0.6) -> int:
    # Let any in-flight messages land before counting, so received reflects
    # actual delivery rather than teardown timing.
    time.sleep(drain_wait)
    total_received = sum(a.received for a in agents)
    for a in agents:
        a.stop()
    time.sleep(0.3)
    return total_received
