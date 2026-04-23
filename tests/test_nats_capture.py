"""
NATS broker capture via transparent TCP proxy
- Starts nats:latest docker on port 4222 (no TLS)
- Python proxy on port 4223 logs every byte forwarded to the broker
- Same plaintext as SLIM test: SLIM_SECURITY_DEMO_PLAINTEXT_2026
- Expected: plaintext IS visible in wire bytes (NATS sends payload unencrypted)
"""

import asyncio
import os
import subprocess
import threading
import time

import nats

from slim_bench.display import B, CY, GR, MG, R, RD, SEP, SEP2, YL, log

PLAINTEXT   = b"SLIM_SECURITY_DEMO_PLAINTEXT_2026"
NATS_PORT   = 4222
PROXY_PORT  = 4223
SUBJECT     = "bench.demo"

CAPTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "captures")
HEXDUMP_FILE = os.path.join(CAPTURES_DIR, "nats_hexdump.txt")

# ── Transparent TCP proxy (same pattern as SLIM test) ─────────────────────────
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
        remote_r, remote_w = await asyncio.open_connection("127.0.0.1", NATS_PORT)
        await asyncio.gather(
            _pipe(local_r, remote_w, "CLIENT→BROKER"),
            _pipe(remote_r, local_w, "BROKER→CLIENT"),
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


# ── Hex dump formatter ─────────────────────────────────────────────────────────
def _hexdump_block(data: bytes, indent: str = "  ") -> list[str]:
    lines = []
    for i in range(0, len(data), 16):
        chunk    = data[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        asc_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{indent}{i:04x}  {hex_part:<47}  |{asc_part}|")
    return lines


# ── NATS pub/sub ───────────────────────────────────────────────────────────────
async def _nats_exchange() -> bytes:
    """Subscribe then publish via the proxy; return received payload."""
    nc  = await nats.connect(f"nats://127.0.0.1:{PROXY_PORT}")
    sub = await nc.subscribe(SUBJECT)
    await asyncio.sleep(0.1)                       # ensure subscription is active

    await nc.publish(SUBJECT, PLAINTEXT)
    log(YL, "PUBLISHER", f"sent  →  {B}{PLAINTEXT!r}{R}")

    msg = await sub.next_msg(timeout=5.0)
    log(GR, "SUBSCRIBER", f"recv  →  {B}{msg.data!r}{R}")

    await nc.drain()
    return msg.data


# ── Docker helpers ─────────────────────────────────────────────────────────────
def _start_nats() -> None:
    log(CY, "DOCKER", "Starting  nats:latest  on port 4222 …")
    subprocess.run(
        ["docker", "run", "--rm", "-d",
         "--name", "nats-bench",
         "-p", "4222:4222",
         "nats:latest"],
        check=True, capture_output=True,
    )
    time.sleep(1.5)  # wait for broker to be ready
    log(CY, "DOCKER", "NATS broker ready")


def _stop_nats() -> None:
    subprocess.run(["docker", "stop", "nats-bench"],
                   capture_output=True)
    log(CY, "DOCKER", "NATS broker stopped")


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    print(SEP2)

    # 1. Start NATS docker
    _start_nats()

    # 2. Start proxy
    log(CY, "PROXY", f"Starting transparent TCP proxy  →  :{PROXY_PORT} → :{NATS_PORT}")
    pt = threading.Thread(target=_proxy_thread_main, daemon=True)
    pt.start()
    time.sleep(0.3)

    # 3. Print known plaintext
    log(CY, "PLAINTEXT", f"string  →  {B}{PLAINTEXT.decode()!r}{R}  ({len(PLAINTEXT)} bytes)")
    log(CY, "PLAINTEXT", f"hex     →  {PLAINTEXT.hex()}")
    print(SEP)

    # 4. Run NATS exchange via proxy
    try:
        received = asyncio.run(_nats_exchange())
        log(MG, "EXCHANGE", f"Message delivered  →  {B}{received!r}{R}")
    except Exception as exc:
        log(RD, "ERROR", str(exc))
        _stop_nats()
        return
    finally:
        time.sleep(0.2)
        if _proxy_server:
            _proxy_server.close()

    # 5. Stop NATS
    _stop_nats()

    # 6. Build hex dump
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
        fh.write(f"NATS broker wire capture\n")
        fh.write(f"Plaintext: {PLAINTEXT.decode()!r}\n")
        fh.write(f"Plaintext hex: {PLAINTEXT.hex()}\n\n")
        fh.write(hexdump_text)
    log(CY, "CAPTURE", f"Hex dump saved  →  {HEXDUMP_FILE}")

    # 7. Search for plaintext
    all_raw   = b"".join(d for _, d in _captured_frames)
    found_raw = PLAINTEXT in all_raw

    print(SEP2)
    log(CY, "CHECK",
        f"Searching for  {B}{PLAINTEXT.decode()!r}{R}  in {total_bytes} wire bytes …")
    if found_raw:
        log(RD, "RESULT", f"EXPOSED — plaintext found verbatim in broker traffic!")
        log(RD, "RESULT",  "  NATS broker sees the full message payload  ✗")
    else:
        log(MG, "RESULT",  "Plaintext NOT found (unexpected)")

    # 8. Print excerpt
    print(SEP)
    print("── Wire bytes at the NATS broker (first 80 lines) ─────────────────")
    for line in dump_lines[:80]:
        print(line)
    print(SEP2)


if __name__ == "__main__":
    main()
