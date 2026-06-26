"""HTTP full-mesh with true process-level parallelism (no SLIM).

The thread-based concurrent mode in http_mesh.py shares one GIL, so the sends
never run Python in parallel — only their socket waits overlap. This module
runs one OS process per agent instead, so concurrency is real parallelism
across cores. On a 12-core laptop, up to ~12 agents send at the same literal
instant; beyond that the OS time-slices them, which is the honest ceiling for
"concurrent on a single laptop".

Each agent process: starts its own HTTP server, opens a keep-alive connection
to every peer, then on a shared barrier fires its full fan-out. Cross-process
barriers gate the phases so every server is up before any send and no server is
torn down while a slower peer is still sending. Per-message samples and received
counts come back through a queue and are pooled into the same MeshResult shape
as the other legs.
"""

from __future__ import annotations

import http.client
import multiprocessing as mp
import statistics
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .display import B, CY, GR, R, YL, log
from .results import MeshResult

HTTP_HOST = "127.0.0.1"
BASE_PORT = 9100


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self.server.received += 1  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


def _agent_proc(idx, n, payload, rounds, ready, go, done, out_q) -> None:
    """One agent: server + sender, living in its own process."""
    server = ThreadingHTTPServer((HTTP_HOST, BASE_PORT + idx), _Handler)
    server.received = 0  # type: ignore[attr-defined]
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()

    ready.wait()  # all servers listening before anyone connects

    conns: dict[int, http.client.HTTPConnection] = {}
    for j in range(n):
        if j != idx:
            c = http.client.HTTPConnection(HTTP_HOST, BASE_PORT + j, timeout=10)
            c.connect()
            conns[j] = c

    samples: list[float] = []
    go.wait()  # every process released together
    for _ in range(rounds):
        for j in range(n):
            if j == idx:
                continue
            c = conns[j]
            t0 = time.perf_counter()
            c.request("POST", "/", body=payload)
            resp = c.getresponse()
            resp.read()
            samples.append((time.perf_counter() - t0) * 1000.0)

    done.wait()  # no server shuts down until every sender has finished
    time.sleep(0.3)  # let the last in-flight requests land
    received = server.received  # type: ignore[attr-defined]
    out_q.put((idx, samples, received))
    for c in conns.values():
        c.close()
    server.shutdown()
    server.server_close()


def run_parallel_http_mesh(n: int, payload: bytes, rounds: int) -> MeshResult:
    """Process-per-agent concurrent full mesh. Always 'concurrent' by nature."""
    ctx = mp.get_context("spawn")  # explicit: matches macOS default, child re-imports
    ready = ctx.Barrier(n)
    go = ctx.Barrier(n)
    done = ctx.Barrier(n)
    out_q: mp.Queue = ctx.Queue()

    expected = n * (n - 1) * rounds
    cores = mp.cpu_count()
    log(YL, "MP-HTTP",
        f"Process-per-agent [{B}parallel{R}]: {B}{n}{R} procs on {B}{cores}{R} cores, "
        f"{B}{n}x{n-1}{R} edges x {B}{rounds}{R} round(s) = {B}{expected}{R} messages")
    if n > cores:
        log(YL, "MP-HTTP",
            f"note: {n} agents > {cores} cores — beyond {cores} the OS time-slices, "
            f"so not all sends are truly simultaneous")

    t0 = time.perf_counter()
    procs = [
        ctx.Process(target=_agent_proc, args=(i, n, payload, rounds, ready, go, done, out_q))
        for i in range(n)
    ]
    for p in procs:
        p.start()

    # Drain the queue before joining so a full pipe never deadlocks the children.
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

    log(GR, "MP-HTTP", f"done in {wall:.1f} ms — {len(all_samples)} sends, {total_received} received")

    return MeshResult(
        name="full_mesh_http_no_slim_parallel",
        samples=all_samples,
        metadata={
            "transport": "http_no_slim",
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
