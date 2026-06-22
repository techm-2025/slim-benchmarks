"""SLIM connection constants, runtime initialisation, and session defaults."""

import datetime
import time

import slim_bindings as slim

from .display import B, CY, R, SEP2, log

SLIM_ENDPOINT = "http://localhost:46357"
SECRET        = "test-secret-key-with-sufficient-length-for-hmac"
PAYLOAD       = b"hello-slim-tests"
TIMEOUT       = datetime.timedelta(seconds=10)


def init_slim() -> slim.Service:
    """Start the SLIM Tokio runtime and return the global service."""
    print(SEP2)
    log(CY, "INIT", f"Connecting to SLIM node  →  {B}{SLIM_ENDPOINT}{R}")

    t0 = time.perf_counter()
    client_cfg   = slim.new_insecure_client_config(SLIM_ENDPOINT)
    dataplane_cfg = slim.DataplaneConfig(servers=[], clients=[client_cfg])
    service_cfg  = slim.new_service_config_with(
        node_id=None, group_name=None, dataplane=dataplane_cfg
    )
    runtime_cfg = slim.new_runtime_config_with(
        n_cores=2,
        thread_name="slim-rt",
        drain_timeout=datetime.timedelta(seconds=10),
    )
    slim.initialize_with_configs(runtime_cfg, slim.new_tracing_config(), [service_cfg])
    time.sleep(0.2)  # allow the connection to be established

    svc     = slim.get_global_service()
    conn_id = svc.get_connection_id(SLIM_ENDPOINT)
    elapsed = (time.perf_counter() - t0) * 1000

    log(CY, "INIT", f"Runtime started  •  n_cores=2  •  thread_name=slim-rt")
    log(CY, "INIT", f"Service          →  {B}{svc.get_name()}{R}")
    log(CY, "INIT", f"Connection ID    →  {B}{conn_id}{R}  ({elapsed:.1f} ms)")
    print(SEP2)
    return svc


def session_cfg() -> slim.SessionConfig:
    return slim.SessionConfig(
        session_type=slim.SessionType.POINT_TO_POINT,
        enable_mls=False,
        max_retries=None,
        interval=None,
        metadata={},
    )
