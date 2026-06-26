"""Full-mesh HTTP benchmark, no SLIM (the mesh-configuration baseline).

Cell 3 of the four-cell transport comparison:
  1. A2A, no SLIM (mesh)
  2. A2A over SLIM
  3. HTTP, no SLIM (mesh)   <-- this file
  4. HTTP over SLIM

Builds N plain HTTP agents on localhost, each a small threaded HTTP server.
Full mesh: every agent holds a keep-alive connection to every other agent and
sends one request per peer per round. Same two execution modes and the same
result shape as slim_bench/mesh.py, so the two transports can be compared
directly off the same evidence JSON.

  * sequential — one request in flight at a time. Per-message latency floor.
  * concurrent — every agent fans out to all peers at once (thread per source).

Connections are opened once in a warm phase (mirrors session warm-up in the
SLIM harness), so per-round timings measure the request path, not connect cost.

Note on what is timed: HTTP has no one-way send. Each measured "message" is a
full request->response round trip at the HTTP layer. The SLIM harness times
publish_and_wait (publish to delivery-confirmed). Keep that asymmetry in mind
when reading the two side by side; it is a property of the transports, not the
harness.
"""

from __future__ import annotations

import http.client
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .display import B, CY, GR, R, RD, YL, log
from .results import MeshResult  # shared result/stats shape

# Loopback host and the base port; agent i listens on BASE_PORT + i.
HTTP_HOST = "127.0.0.1"
BASE_PORT = 9100


class _Handler(BaseHTTPRequestHandler):
    """Reads the request body, bumps the owning agent's counter, returns 200."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self.server.received += 1  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        pass  # silence the default stderr access log


class HttpMeshAgent:
    """One HTTP server (receiver) plus cached client connections (sender)."""

    def __init__(self, idx: int) -> None:
        self.idx = idx
        self.port = BASE_PORT + idx
        self.server = ThreadingHTTPServer((HTTP_HOST, self.port), _Handler)
        self.server.received = 0  # type: ignore[attr-defined]
        self.conns: dict[int, http.client.HTTPConnection] = {}  # dest idx -> conn
        self._serve_thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def received(self) -> int:
        return self.server.received  # type: ignore[attr-defined]

    def start_receiver(self) -> None:
        self._serve_thread.start()

    def open_session_to(self, dest: "HttpMeshAgent") -> float:
        """Open and cache a keep-alive connection to dest. Returns connect ms."""
        t0 = time.perf_counter()
        conn = http.client.HTTPConnection(HTTP_HOST, dest.port, timeout=10)
        conn.connect()
        self.conns[dest.idx] = conn
        return (time.perf_counter() - t0) * 1000.0

    def publish_to(self, dest_idx: int, payload: bytes) -> float:
        """Send one request on the cached connection. Returns round-trip ms."""
        conn = self.conns[dest_idx]
        t0 = time.perf_counter()
        conn.request("POST", "/", body=payload)
        resp = conn.getresponse()
        resp.read()  # drain so the connection can be reused
        return (time.perf_counter() - t0) * 1000.0

    def stop(self) -> None:
        for conn in self.conns.values():
            try:
                conn.close()
            except Exception:
                pass
        self.server.shutdown()
        self.server.server_close()


def build_http_mesh(n: int) -> list[HttpMeshAgent]:
    log(CY, "HTTP", f"Building {B}{n}{R} HTTP agents on {HTTP_HOST}:{BASE_PORT}..{BASE_PORT + n - 1}")
    agents = [HttpMeshAgent(i) for i in range(n)]
    for a in agents:
        a.start_receiver()
    time.sleep(0.5)  # let every server reach serve_forever before any send
    log(GR, "HTTP", f"All {B}{n}{R} servers listening")
    return agents


def warm_connections(agents: list[HttpMeshAgent]) -> list[float]:
    """Open every directed connection once. Returns per-connection connect ms."""
    setup: list[float] = []
    for src in agents:
        for dst in agents:
            if src.idx != dst.idx:
                setup.append(src.open_session_to(dst))
    log(GR, "HTTP", f"Warmed {B}{len(setup)}{R} connections (connect mean {statistics.mean(setup):.2f} ms)")
    return setup


def _run_sequential(agents: list[HttpMeshAgent], payload: bytes) -> list[float]:
    samples: list[float] = []
    for src in agents:
        for dst in agents:
            if src.idx != dst.idx:
                try:
                    samples.append(src.publish_to(dst.idx, payload))
                except Exception as exc:
                    log(RD, "HTTP", f"send {src.idx}->{dst.idx} failed: {exc}")
    return samples


def _run_concurrent(agents: list[HttpMeshAgent], payload: bytes) -> list[float]:
    # One thread per source; every source released together so the receivers
    # see simultaneous load. Each cached connection is touched by exactly one
    # source thread, so no connection is shared across threads.
    per_thread: list[list[float]] = [[] for _ in agents]
    barrier = threading.Barrier(len(agents))

    def worker(src: HttpMeshAgent, sink: list[float]) -> None:
        barrier.wait()
        for dst in agents:
            if src.idx != dst.idx:
                try:
                    sink.append(src.publish_to(dst.idx, payload))
                except Exception as exc:
                    log(RD, "HTTP", f"send {src.idx}->{dst.idx} failed: {exc}")

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


def run_full_http_mesh(
    agents: list[HttpMeshAgent],
    payload: bytes,
    rounds: int,
    concurrent: bool,
) -> MeshResult:
    n = len(agents)
    mode = "concurrent" if concurrent else "sequential"
    expected = n * (n - 1) * rounds
    log(YL, "HTTP",
        f"Full-mesh [{B}{mode}{R}]: {B}{n}x{n-1}{R} edges x {B}{rounds}{R} round(s) = {B}{expected}{R} messages")

    samples: list[float] = []
    round_wall: list[float] = []
    runner = _run_concurrent if concurrent else _run_sequential
    for r in range(rounds):
        t0 = time.perf_counter()
        samples.extend(runner(agents, payload))
        round_wall.append((time.perf_counter() - t0) * 1000.0)
        log(CY, "HTTP", f"round {r + 1}/{rounds} done in {round_wall[-1]:.1f} ms — {len(samples)} sends total")

    return MeshResult(
        name=f"full_mesh_http_no_slim_{mode}",
        samples=samples,
        metadata={
            "transport": "http_no_slim",
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


def teardown_http_mesh(agents: list[HttpMeshAgent], drain_wait: float = 0.6) -> int:
    # Let any in-flight requests land before counting received.
    time.sleep(drain_wait)
    total_received = sum(a.received for a in agents)
    for a in agents:
        a.stop()
    return total_received
