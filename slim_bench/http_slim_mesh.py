"""Full-mesh HTTP-over-SLIM (cell 4): HTTP request/response carried over SLIM.

Cell 4 of the four-cell comparison:
  1. A2A, no SLIM (mesh)
  2. A2A over SLIM
  3. HTTP, no SLIM (mesh)
  4. HTTP over SLIM        <-- this file

Instead of an HTTP socket, each agent tunnels an HTTP-style request/response
pair through a SLIM point-to-point session (the same encapsulation idea as the
A2A-over-SLIM tunnel). One measured message is a full round trip: the sender
publishes a request payload, the receiver replies on the same session via
publish_to, and the sender waits for that reply. This matches the round-trip
timing of the HTTP-no-SLIM leg, so cells 3 and 4 are directly comparable.

Three modes mirror the other legs: sequential, concurrent (threads), and
parallel (process per agent, in mp_http_slim_mesh.py).
"""

from __future__ import annotations

import datetime
import statistics
import threading
import time

import slim_bindings as slim

from .config import SECRET, session_cfg
from .display import B, CY, GR, R, RD, YL, log
from .results import MeshResult

RECV_POLL = datetime.timedelta(seconds=2)

# Minimal HTTP-style request/response lines carried as the SLIM payload. The
# body is padded to the requested size so payload scaling matches the HTTP leg.
_REQ_HEAD = b"GET / HTTP/1.1\r\nhost: slim\r\n\r\n"
_RESP_HEAD = b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n"


class HttpSlimAgent:
    """A SLIM app that answers inbound requests and sends outbound requests."""

    def __init__(self, svc: slim.Service, conn_id: int, idx: int, secret: str, tag: str) -> None:
        self.idx = idx
        self.conn_id = conn_id
        self.name = slim.Name("org", tag, f"agent-{idx}")
        self.app = svc.create_app_with_secret(self.name, secret)
        self.app.subscribe(self.name, conn_id)

        self.served = 0  # requests answered as a server
        self.sessions: dict[int, slim.Session] = {}  # dest idx -> outbound session
        self._stop = threading.Event()
        self._recv_thread = threading.Thread(target=self._serve_loop, daemon=True)

    def start_server(self) -> None:
        self._recv_thread.start()

    def _serve_loop(self) -> None:
        # Accept inbound sessions; answer every request with a response payload.
        while not self._stop.is_set():
            try:
                session = self.app.listen_for_session(RECV_POLL)
            except Exception:
                continue
            t = threading.Thread(target=self._answer, args=(session,), daemon=True)
            t.start()

    def _answer(self, session: slim.Session) -> None:
        while not self._stop.is_set():
            try:
                msg = session.get_message(RECV_POLL)
            except Exception:
                break
            try:
                session.publish_to(msg.context, _RESP_HEAD, None, None)
                self.served += 1
            except Exception:
                break

    def open_session_to(self, dest: "HttpSlimAgent") -> float:
        t0 = time.perf_counter()
        self.app.set_route(dest.name, self.conn_id)
        self.sessions[dest.idx] = self.app.create_session_and_wait(session_cfg(), dest.name)
        return (time.perf_counter() - t0) * 1000.0

    def request_to(self, dest_idx: int, payload: bytes) -> float:
        """Send one request and wait for the reply. Returns round-trip ms."""
        session = self.sessions[dest_idx]
        t0 = time.perf_counter()
        session.publish_and_wait(payload, None, None)
        session.get_message(RECV_POLL)  # the response
        return (time.perf_counter() - t0) * 1000.0

    def stop(self) -> None:
        self._stop.set()


def build_http_slim_mesh(svc, conn_id, n, secret=SECRET, tag="hslim") -> list[HttpSlimAgent]:
    log(CY, "HTTP-SLIM", f"Building {B}{n}{R} agents on conn_id={B}{conn_id}{R} (tag={tag})")
    agents = [HttpSlimAgent(svc, conn_id, i, secret, tag) for i in range(n)]
    for a in agents:
        a.start_server()
    time.sleep(0.5)
    log(GR, "HTTP-SLIM", f"All {B}{n}{R} agents subscribed and serving")
    return agents


def warm_sessions(agents: list[HttpSlimAgent]) -> list[float]:
    setup: list[float] = []
    for src in agents:
        for dst in agents:
            if src.idx != dst.idx:
                setup.append(src.open_session_to(dst))
    log(GR, "HTTP-SLIM", f"Warmed {B}{len(setup)}{R} sessions (setup mean {statistics.mean(setup):.2f} ms)")
    return setup


def _payload(size: int) -> bytes:
    body = b"x" * max(0, size - len(_REQ_HEAD))
    return _REQ_HEAD + body


def _run_sequential(agents: list[HttpSlimAgent], payload: bytes) -> list[float]:
    samples: list[float] = []
    for src in agents:
        for dst in agents:
            if src.idx != dst.idx:
                try:
                    samples.append(src.request_to(dst.idx, payload))
                except Exception as exc:
                    log(RD, "HTTP-SLIM", f"req {src.idx}->{dst.idx} failed: {exc}")
    return samples


def _run_concurrent(agents: list[HttpSlimAgent], payload: bytes) -> list[float]:
    per_thread: list[list[float]] = [[] for _ in agents]
    barrier = threading.Barrier(len(agents))

    def worker(src: HttpSlimAgent, sink: list[float]) -> None:
        barrier.wait()
        for dst in agents:
            if src.idx != dst.idx:
                try:
                    sink.append(src.request_to(dst.idx, payload))
                except Exception as exc:
                    log(RD, "HTTP-SLIM", f"req {src.idx}->{dst.idx} failed: {exc}")

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


def run_full_http_slim_mesh(agents, payload, rounds, concurrent) -> MeshResult:
    n = len(agents)
    mode = "concurrent" if concurrent else "sequential"
    expected = n * (n - 1) * rounds
    log(YL, "HTTP-SLIM",
        f"Full-mesh [{B}{mode}{R}]: {B}{n}x{n-1}{R} edges x {B}{rounds}{R} round(s) = {B}{expected}{R} round trips")

    samples: list[float] = []
    round_wall: list[float] = []
    runner = _run_concurrent if concurrent else _run_sequential
    for r in range(rounds):
        t0 = time.perf_counter()
        samples.extend(runner(agents, payload))
        round_wall.append((time.perf_counter() - t0) * 1000.0)
        log(CY, "HTTP-SLIM", f"round {r + 1}/{rounds} done in {round_wall[-1]:.1f} ms — {len(samples)} round trips total")

    return MeshResult(
        name=f"full_mesh_http_over_slim_{mode}",
        samples=samples,
        metadata={
            "transport": "http_over_slim",
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


def teardown_http_slim_mesh(agents: list[HttpSlimAgent], drain_wait: float = 0.6) -> int:
    time.sleep(drain_wait)
    total_served = sum(a.served for a in agents)
    for a in agents:
        a.stop()
    time.sleep(0.3)
    return total_served
