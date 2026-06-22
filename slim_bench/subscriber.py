"""Subscriber participant — registers a name and receives one message."""

import threading
import time

import slim_bindings as slim

from .config import SECRET, TIMEOUT
from .display import B, GR, R, RD, log


def run_subscriber(
    svc: slim.Service,
    conn_id: int,
    received: list,
    ready: threading.Event,
    error: list,
) -> None:
    role = "SUBSCRIBER"
    try:
        name = slim.Name("org", "test", "subscriber")
        log(GR, role, f"Creating app     →  {B}{name}{R}")

        t0  = time.perf_counter()
        app = svc.create_app_with_secret(name, SECRET)
        log(GR, role, f"App created      →  app_id={B}{app.id()}{R}  ({(time.perf_counter()-t0)*1000:.1f} ms)")

        t0 = time.perf_counter()
        app.subscribe(name, conn_id)
        log(GR, role, f"Subscribed       →  name={B}{name}{R}  conn_id={B}{conn_id}{R}  ({(time.perf_counter()-t0)*1000:.1f} ms)")

        ready.set()
        log(GR, role, "Ready signal sent — waiting for inbound session …")

        t0      = time.perf_counter()
        session = app.listen_for_session(TIMEOUT)
        log(GR, role,
            f"Session accepted →  session_id={B}{session.session_id()}{R}"
            f"  type={B}{session.session_type()}{R}"
            f"  ({(time.perf_counter()-t0)*1000:.1f} ms)")
        log(GR, role, f"  source    →  {session.source()}")
        log(GR, role, f"  dest      →  {session.destination()}")

        t0  = time.perf_counter()
        msg = session.get_message(TIMEOUT)
        log(GR, role, f"Message received →  {(time.perf_counter()-t0)*1000:.1f} ms")
        log(GR, role, f"  payload   →  {B}{msg.payload.decode(errors='replace')!r}{R}")
        log(GR, role, f"  length    →  {B}{len(msg.payload)}{R} bytes")
        log(GR, role, f"  raw       →  {msg.payload.hex()}")

        received.append(msg.payload)

    except Exception as exc:
        log(RD, role, f"ERROR: {exc}")
        error.append(exc)
        ready.set()
