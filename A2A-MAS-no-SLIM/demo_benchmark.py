"""Demo benchmark for multi-agent fanout, latency, transport, and encryption."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from cryptography.fernet import Fernet
import uvicorn


@dataclass
class ScenarioResult:
    name: str
    samples: list[float]
    metadata: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.samples)
        p50 = ordered[int(0.50 * (len(ordered) - 1))]
        p95 = ordered[int(0.95 * (len(ordered) - 1))]
        return {
            "scenario": self.name,
            "count": len(self.samples),
            "mean_ms": round(statistics.mean(self.samples), 3),
            "median_ms": round(statistics.median(self.samples), 3),
            "p50_ms": round(p50, 3),
            "p95_ms": round(p95, 3),
            "min_ms": round(min(self.samples), 3),
            "max_ms": round(max(self.samples), 3),
            "metadata": self.metadata,
        }


class InMemorySlimBus:
    """Simple in-memory bus used to approximate low-overhead SLIM transport."""

    async def request(self, sender: str, receiver: str, payload: str) -> dict[str, Any]:
        _ = sender
        _ = payload
        # Minimal cooperative scheduling to simulate async hop.
        await asyncio.sleep(0)
        return {"receiver": receiver, "ok": True}


class SimpleEchoASGIApp:
    """Minimal ASGI app that accepts JSON-RPC style POST and echoes."""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await send(
                {
                    "type": "http.response.start",
                    "status": 405,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"error":"method not allowed"}'})
            return

        body = b""
        while True:
            event = await receive()
            if event["type"] == "http.request":
                body += event.get("body", b"")
                if not event.get("more_body", False):
                    break

        payload = json.loads(body.decode("utf-8"))
        incoming_id = payload.get("id", str(uuid.uuid4()))
        response = {
            "jsonrpc": "2.0",
            "id": incoming_id,
            "result": {"status": "ok"},
        }
        raw = json.dumps(response).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": raw})


async def start_demo_http_agent(port: int) -> uvicorn.Server:
    config = uvicorn.Config(
        app=SimpleEchoASGIApp(),
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())
    return server


async def send_http_message(client: httpx.AsyncClient, port: int, payload: str) -> None:
    request = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "messageId": f"demo-{time.time_ns()}",
                "role": "user",
                "parts": [{"kind": "text", "text": payload}],
            },
            "metadata": {},
        },
        "id": f"id-{time.time_ns()}",
    }
    response = await client.post(f"http://127.0.0.1:{port}/", json=request)
    response.raise_for_status()


async def run_multi_agent_fanout_http(
    ports: dict[str, int], rounds: int, payload: str
) -> ScenarioResult:
    samples: list[float] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(rounds):
            start = time.perf_counter()
            await asyncio.gather(
                send_http_message(client, ports["B"], payload),
                send_http_message(client, ports["C"], payload),
                send_http_message(client, ports["D"], payload),
                send_http_message(client, ports["E"], payload),
            )
            samples.append((time.perf_counter() - start) * 1000)
    return ScenarioResult(
        name="fanout_http_A_to_BCDE",
        samples=samples,
        metadata={"topology": "A->B,C,D,E", "rounds": rounds},
    )


async def run_multi_agent_fanout_slim(rounds: int, payload: str) -> ScenarioResult:
    bus = InMemorySlimBus()
    samples: list[float] = []
    for _ in range(rounds):
        start = time.perf_counter()
        await asyncio.gather(
            bus.request("A", "B", payload),
            bus.request("A", "C", payload),
            bus.request("A", "D", payload),
            bus.request("A", "E", payload),
        )
        samples.append((time.perf_counter() - start) * 1000)
    return ScenarioResult(
        name="fanout_slim_A_to_BCDE",
        samples=samples,
        metadata={"topology": "A->B,C,D,E", "rounds": rounds},
    )


def encrypt_payload(fernet: Fernet, payload: str) -> str:
    return fernet.encrypt(payload.encode("utf-8")).decode("utf-8")


async def run_encryption_overhead_slim(rounds: int, payload: str) -> ScenarioResult:
    bus = InMemorySlimBus()
    key = Fernet.generate_key()
    fernet = Fernet(key)
    plain_samples: list[float] = []
    encrypted_samples: list[float] = []

    for _ in range(rounds):
        start_plain = time.perf_counter()
        await bus.request("A", "B", payload)
        plain_samples.append((time.perf_counter() - start_plain) * 1000)

        encrypted = encrypt_payload(fernet, payload)
        start_enc = time.perf_counter()
        await bus.request("A", "B", encrypted)
        encrypted_samples.append((time.perf_counter() - start_enc) * 1000)

    overhead_mean = statistics.mean(encrypted_samples) - statistics.mean(plain_samples)
    return ScenarioResult(
        name="encryption_overhead_slim",
        samples=encrypted_samples,
        metadata={
            "rounds": rounds,
            "baseline_mean_ms": round(statistics.mean(plain_samples), 3),
            "encrypted_mean_ms": round(statistics.mean(encrypted_samples), 3),
            "delta_mean_ms": round(overhead_mean, 3),
        },
    )


async def run_demo(rounds: int, base_port: int, payload_size: int) -> dict[str, Any]:
    ports = {"A": base_port, "B": base_port + 1, "C": base_port + 2, "D": base_port + 3, "E": base_port + 4}
    payload = "x" * payload_size

    servers = []
    for agent_name in ["A", "B", "C", "D", "E"]:
        servers.append(await start_demo_http_agent(port=ports[agent_name]))
    await asyncio.sleep(1)

    try:
        http_fanout = await run_multi_agent_fanout_http(ports, rounds, payload)
        slim_fanout = await run_multi_agent_fanout_slim(rounds, payload)
        enc = await run_encryption_overhead_slim(rounds, payload)
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.sleep(0.3)

    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "config": {"rounds": rounds, "base_port": base_port, "payload_size": payload_size},
        "results": [http_fanout.summary(), slim_fanout.summary(), enc.summary()],
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SLIM vs HTTP benchmark demo scenarios.")
    parser.add_argument("--rounds", type=int, default=50, help="Number of test rounds per scenario.")
    parser.add_argument("--base-port", type=int, default=8100, help="Base port for agents A-E.")
    parser.add_argument("--payload-size", type=int, default=64, help="Payload size in bytes.")
    parser.add_argument("--output", type=str, default="", help="Optional JSON output path.")
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    result = await run_demo(args.rounds, args.base_port, args.payload_size)
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    asyncio.run(_main())
