"""
Connectivity test: one subscriber, one publisher, assert receipt.
"""

import threading
import time

from slim_bench.config import PAYLOAD, TIMEOUT, init_slim
from slim_bench.display import B, CY, MG, R, RD, SEP, SEP2, log
from slim_bench.publisher import run_publisher
from slim_bench.subscriber import run_subscriber


def test_pub_sub_connectivity() -> None:
    svc     = init_slim()
    conn_id = svc.get_connection_id("http://localhost:46357")
    assert conn_id is not None, "Not connected to SLIM node"

    received: list = []
    errors:   list = []
    ready = threading.Event()

    print(SEP)
    log(CY, "TEST", "Launching subscriber and publisher threads")
    t_start = time.perf_counter()

    sub_thread = threading.Thread(
        target=run_subscriber,
        args=(svc, conn_id, received, ready, errors),
        daemon=True,
    )
    pub_thread = threading.Thread(
        target=run_publisher,
        args=(svc, ready, errors),
        daemon=True,
    )

    sub_thread.start()
    pub_thread.start()
    pub_thread.join(timeout=TIMEOUT.total_seconds())
    sub_thread.join(timeout=TIMEOUT.total_seconds())

    total_ms = (time.perf_counter() - t_start) * 1000
    print(SEP)

    if errors:
        for e in errors:
            log(RD, "ERROR", str(e))
        raise AssertionError(f"Thread(s) raised errors: {errors}")

    assert received, "Subscriber received no messages"
    assert received[0] == PAYLOAD, (
        f"Payload mismatch: expected {PAYLOAD!r}, got {received[0]!r}"
    )

    log(MG, "RESULT", f"{B}PASS{R}")
    log(MG, "RESULT", f"  payload match  →  {B}{received[0]!r}{R}  ==  {B}{PAYLOAD!r}{R}")
    log(MG, "RESULT", f"  total time     →  {B}{total_ms:.1f} ms{R}")
    print(SEP2)


if __name__ == "__main__":
    test_pub_sub_connectivity()
