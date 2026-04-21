"""Publisher participant — opens a session to the subscriber and sends one message."""

import threading
import time

import slim_bindings as slim

from .config import PAYLOAD, SECRET, TIMEOUT, session_cfg
from .display import B, R, RD, YL, log


def run_publisher(
    svc: slim.Service,
    ready: threading.Event,
    error: list,
) -> None:
    role = "PUBLISHER"
    log(YL, role, "Waiting for subscriber to be ready …")

    if not ready.wait(timeout=TIMEOUT.total_seconds()):
        error.append(TimeoutError("Subscriber did not become ready"))
        return

    # Brief pause so listen_for_session is active before the discovery request.
    time.sleep(0.2)

    try:
        name = slim.Name("org", "test", "publisher")
        log(YL, role, f"Creating app     →  {B}{name}{R}")

        t0  = time.perf_counter()
        app = svc.create_app_with_secret(name, SECRET)
        log(YL, role, f"App created      →  app_id={B}{app.id()}{R}  ({(time.perf_counter()-t0)*1000:.1f} ms)")

        dest = slim.Name("org", "test", "subscriber")
        log(YL, role, f"Opening session  →  dest={B}{dest}{R}  type=POINT_TO_POINT")

        t0      = time.perf_counter()
        session = app.create_session_and_wait(session_cfg(), dest)
        log(YL, role,
            f"Session opened   →  session_id={B}{session.session_id()}{R}"
            f"  ({(time.perf_counter()-t0)*1000:.1f} ms)")
        log(YL, role, f"  source    →  {session.source()}")
        log(YL, role, f"  dest      →  {session.destination()}")

        log(YL, role,
            f"Publishing       →  payload={B}{PAYLOAD.decode(errors='replace')!r}{R}"
            f"  length={B}{len(PAYLOAD)}{R} bytes  raw={PAYLOAD.hex()}")

        t0 = time.perf_counter()
        session.publish_and_wait(PAYLOAD, None, None)
        log(YL, role, f"Publish complete →  {(time.perf_counter()-t0)*1000:.1f} ms  (delivery confirmed)")

    except Exception as exc:
        log(RD, role, f"ERROR: {exc}")
        error.append(exc)
