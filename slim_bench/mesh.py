"""Full-mesh SLIM benchmark over a real SLIM node.

Builds N real SLIM apps (agents) on the live broker and runs a full-mesh round:
every agent opens a POINT_TO_POINT session to every other agent and publishes
one message. Per-message publish latency (delivery confirmed) is collected.

Unlike the in-memory `InMemorySlimBus` in A2A-MAS-no-SLIM/demo_benchmark.py,
this exercises the actual SLIM dataplane through `slim-bindings`.
"""

from __future__ import annotations

import datetime
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import slim_bindings as slim

from .config import SECRET, session_cfg
from .display import B, CY, GR, R, RD, YL, log

# Short poll timeout for receiver loops so they can notice the stop flag.
RECV_POLL = datetime.timedelta(seconds=2)


class MeshAgent:
    """One SLIM app that both receives (any peer) and sends (to any peer)."""

    def __init__(self, svc: slim.Service, conn_id: int, idx: int, secret: str) -> None:
        self.idx = idx
        self.name = slim.Name("org", "mesh", f"agent-{idx}")
        self.app = svc.create_app_with_secret(self.name, secret)
        self.app.subscribe(self.name, conn_id)

        self.received = 0
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

    def send_to(self, dest: "MeshAgent", payload: bytes) -> float:
        """Open a session to dest, publish one message, return publish ms."""
        session = self.app.create_session_and_wait(session_cfg(), dest.name)
        t0 = time.perf_counter()
        session.publish_and_wait(payload, None, None)
        return (time.perf_counter() - t0) * 1000.0

    def stop(self) -> None:
        self._stop.set()


@dataclass
class MeshResult:
    name: str
    samples: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.samples)
        n = len(ordered)
        p = lambda q: ordered[int(q * (n - 1))] if n else 0.0
        return {
            "scenario": self.name,
            "count": n,
            "mean_ms": round(statistics.mean(self.samples), 3) if n else 0.0,
            "median_ms": round(statistics.median(self.samples), 3) if n else 0.0,
            "p50_ms": round(p(0.50), 3),
            "p95_ms": round(p(0.95), 3),
            "min_ms": round(min(self.samples), 3) if n else 0.0,
            "max_ms": round(max(self.samples), 3) if n else 0.0,
            "metadata": self.metadata,
        }


def build_mesh(svc: slim.Service, conn_id: int, n: int, secret: str = SECRET) -> list[MeshAgent]:
    log(CY, "MESH", f"Building {B}{n}{R} agents on conn_id={B}{conn_id}{R}")
    agents = [MeshAgent(svc, conn_id, i, secret) for i in range(n)]
    for a in agents:
        a.start_receiver()
    # Give every receiver a moment to reach listen_for_session before any send.
    time.sleep(0.5)
    log(GR, "MESH", f"All {B}{n}{R} agents subscribed and listening")
    return agents


def run_full_mesh_round(agents: list[MeshAgent], payload: bytes, rounds: int) -> MeshResult:
    n = len(agents)
    samples: list[float] = []
    expected = n * (n - 1) * rounds
    log(YL, "MESH", f"Full-mesh: {B}{n}x{n-1}{R} directed edges x {B}{rounds}{R} round(s) = {B}{expected}{R} messages")

    for r in range(rounds):
        for i, src in enumerate(agents):
            for j, dst in enumerate(agents):
                if i == j:
                    continue
                try:
                    samples.append(src.send_to(dst, payload))
                except Exception as exc:
                    log(RD, "MESH", f"send {i}->{j} failed: {exc}")
        log(CY, "MESH", f"round {r + 1}/{rounds} done — {len(samples)} sends so far")

    return MeshResult(
        name="full_mesh_slim_unicast",
        samples=samples,
        metadata={
            "transport": "slim_unicast_point_to_point",
            "agents": n,
            "rounds": rounds,
            "directed_edges": n * (n - 1),
            "expected_messages": expected,
            "payload_bytes": len(payload),
        },
    )


def teardown_mesh(agents: list[MeshAgent]) -> int:
    total_received = sum(a.received for a in agents)
    for a in agents:
        a.stop()
    time.sleep(0.3)
    return total_received
