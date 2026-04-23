"""
SLIM relay capture via transparent TCP proxy
- A Python proxy on port 46360 forwards to SLIM node on port 46357
- Every byte passing through is logged (no sudo / interface guessing needed)
- Known plaintext: SLIM_SECURITY_DEMO_PLAINTEXT_2026
- Expected: plaintext NOT visible in wire bytes (end-to-end encrypted at relay)
"""

import asyncio
import datetime
import os
import threading
import time

import slim_bindings as slim

from slim_bench.config import SECRET, TIMEOUT, session_cfg
from slim_bench.display import B, CY, GR, MG, R, RD, SEP, SEP2, YL, log

PLAINTEXT      = b"SLIM_SECURITY_DEMO_PLAINTEXT_2026"
SLIM_PORT      = 46357
PROXY_PORT     = 46360
PROXY_ENDPOINT = f"http://localhost:{PROXY_PORT}"

CAPTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "captures")
HEXDUMP_FILE = os.path.join(CAPTURES_DIR, "slim_hexdump.txt")

# ── Transparent TCP proxy ──────────────────────────────────────────────────────
_captured_frames: list[tuple[str, bytes]] = []
_proxy_server = None
_proxy_loop   = None


async def _pipe(reader, writer, direction: str) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            _captured_frames.append((direction, data))
            writer.write(data)
            await writer.drain()
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _handle(local_r, local_w) -> None:
    try:
        remote_r, remote_w = await asyncio.open_connection("127.0.0.1", SLIM_PORT)
        await asyncio.gather(
            _pipe(local_r, remote_w, "CLIENT→RELAY"),
            _pipe(remote_r, local_w, "RELAY→CLIENT"),
        )
    except Exception:
        pass


async def _serve() -> None:
    global _proxy_server
    _proxy_server = await asyncio.start_server(_handle, "127.0.0.1", PROXY_PORT)
    await _proxy_server.serve_forever()


def _proxy_thread_main() -> None:
    global _proxy_loop
    _proxy_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_proxy_loop)
    _proxy_loop.run_until_complete(_serve())


# ── SLIM helpers ───────────────────────────────────────────────────────────────
def _init_slim_via_proxy() -> slim.Service:
    log(CY, "INIT", f"Connecting via proxy  →  {B}{PROXY_ENDPOINT}{R}")
    client_cfg    = slim.new_insecure_client_config(PROXY_ENDPOINT)
    dataplane_cfg = slim.DataplaneConfig(servers=[], clients=[client_cfg])
    service_cfg   = slim.new_service_config_with(node_id=None, group_name=None, dataplane=dataplane_cfg)
    runtime_cfg   = slim.new_runtime_config_with(
        n_cores=2, thread_name="slim-rt",
        drain_timeout=datetime.timedelta(seconds=10),
    )
    slim.initialize_with_configs(runtime_cfg, slim.new_tracing_config(), [service_cfg])
    time.sleep(0.2)
    svc     = slim.get_global_service()
    conn_id = svc.get_connection_id(PROXY_ENDPOINT)
    log(CY, "INIT", f"Connection ID    →  {B}{conn_id}{R}")
    return svc


def _subscriber(svc, conn_id, received, ready, errors):
    try:
        name = slim.Name("org", "demo", "sub")
        app  = svc.create_app_with_secret(name, SECRET)
        app.subscribe(name, conn_id)
        ready.set()
        session = app.listen_for_session(TIMEOUT)
        msg     = session.get_message(TIMEOUT)
        received.append(msg.payload)
        log(GR, "SUBSCRIBER", f"received  →  {B}{msg.payload!r}{R}")
    except Exception as exc:
        errors.append(exc)
        ready.set()


def _publisher(svc, ready, errors):
    try:
        if not ready.wait(timeout=TIMEOUT.total_seconds()):
            errors.append(TimeoutError("subscriber not ready"))
            return
        time.sleep(0.2)
        name    = slim.Name("org", "demo", "pub")
        app     = svc.create_app_with_secret(name, SECRET)
        dest    = slim.Name("org", "demo", "sub")
        session = app.create_session_and_wait(session_cfg(), dest)
        session.publish_and_wait(PLAINTEXT, None, None)
        log(YL, "PUBLISHER", f"sent      →  {B}{PLAINTEXT!r}{R}")
    except Exception as exc:
        errors.append(exc)


# ── Hex dump formatter ─────────────────────────────────────────────────────────
def _hexdump_block(data: bytes, indent: str = "  ") -> list[str]:
    lines = []
    for i in range(0, len(data), 16):
        chunk    = data[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        asc_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{indent}{i:04x}  {hex_part:<47}  |{asc_part}|")
    return lines


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    print(SEP2)

    # 1. Start proxy
    log(CY, "PROXY", f"Starting transparent TCP proxy  →  :{PROXY_PORT} → :{SLIM_PORT}")
    pt = threading.Thread(target=_proxy_thread_main, daemon=True)
    pt.start()
    time.sleep(0.3)

    # 2. Print the known plaintext we're about to send
    log(CY, "PLAINTEXT", f"string  →  {B}{PLAINTEXT.decode()!r}{R}  ({len(PLAINTEXT)} bytes)")
    log(CY, "PLAINTEXT", f"hex     →  {PLAINTEXT.hex()}")
    print(SEP)

    # 3. SLIM exchange via proxy
    svc     = _init_slim_via_proxy()
    conn_id = svc.get_connection_id(PROXY_ENDPOINT)

    received, errors, ready = [], [], threading.Event()
    sub = threading.Thread(target=_subscriber, args=(svc, conn_id, received, ready, errors), daemon=True)
    pub = threading.Thread(target=_publisher,  args=(svc, ready, errors),                   daemon=True)
    sub.start()
    pub.start()
    pub.join(timeout=TIMEOUT.total_seconds())
    sub.join(timeout=TIMEOUT.total_seconds())

    if errors:
        for e in errors:
            log(RD, "ERROR", str(e))
        return

    log(MG, "EXCHANGE", f"Message delivered  →  {B}{received[0]!r}{R}")
    time.sleep(0.2)

    # 4. Stop proxy
    if _proxy_server:
        _proxy_server.close()

    # 5. Build hex dump from captured frames
    total_bytes = sum(len(d) for _, d in _captured_frames)
    log(CY, "CAPTURE",
        f"Captured {len(_captured_frames)} frames  •  {total_bytes} bytes total")

    dump_lines: list[str] = []
    for direction, data in _captured_frames:
        dump_lines.append(f"{'─'*64}")
        dump_lines.append(f"  [{direction}]  {len(data)} bytes")
        dump_lines.extend(_hexdump_block(data))

    hexdump_text = "\n".join(dump_lines)
    with open(HEXDUMP_FILE, "w") as fh:
        fh.write(f"SLIM relay wire capture\n")
        fh.write(f"Plaintext: {PLAINTEXT.decode()!r}\n")
        fh.write(f"Plaintext hex: {PLAINTEXT.hex()}\n\n")
        fh.write(hexdump_text)
    log(CY, "CAPTURE", f"Hex dump saved  →  {HEXDUMP_FILE}")

    # 6. Search for plaintext in the captured bytes
    needle     = PLAINTEXT.decode()
    all_raw    = b"".join(d for _, d in _captured_frames)
    found_raw  = PLAINTEXT in all_raw          # exact bytes in wire stream
    found_dump = needle in hexdump_text        # string in ASCII column of dump

    print(SEP2)
    log(CY, "CHECK",
        f"Searching for  {B}{needle!r}{R}  in {total_bytes} wire bytes …")
    if found_raw or found_dump:
        log(RD, "RESULT", "FAIL — plaintext visible in relay traffic!")
        log(RD, "RESULT", f"  byte-level match : {found_raw}")
        log(RD, "RESULT", f"  ASCII-col match  : {found_dump}")
    else:
        log(MG, "RESULT", f"PASS — {B}'{needle}'{R} NOT found in {total_bytes} relay bytes")
        log(MG, "RESULT",  "  The relay only sees ciphertext  ✓")

    # 7. Print excerpt for visual inspection
    print(SEP)
    print("── Wire bytes at the relay (first 80 lines) ───────────────────────")
    for line in dump_lines[:80]:
        print(line)
    print(SEP2)


if __name__ == "__main__":
    main()
