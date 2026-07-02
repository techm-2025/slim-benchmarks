"""A2A-over-SLIM full mesh benchmark (cell 2), using the public slima2a package.

Each agent is its own OS process (true parallelism).  Inside each process:
  - SLIM is initialized via slima2a.initialize_slim_service (sets uniffi event loop)
  - An echo A2A server is registered via SRPCHandler + slim_bindings.Server
  - Per-peer A2A clients are created via SRPCTransport + ClientFactory
  - Timing: one measured unit = full SendMessage round trip (request → ClientEvent)

Requires:
  - slima2a==0.6.0  (pip)
  - slim-bindings==1.4.1  (pip)
  - a2a-sdk[sqlite,telemetry]==1.0.0-alpha.0  (pip)
  - SLIM node: ghcr.io/agntcy/slim:1.4.0  (docker)
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import time
import uuid

import slim_bindings
from a2a.client import ClientFactory
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types.a2a_pb2 import (
    AgentCard as ProtoAgentCard,
    Part,
    Role,
    SendMessageRequest,
)
from a2a.utils.errors import UnsupportedOperationError

from slima2a import connect_and_subscribe, initialize_slim_service
from slima2a.client_transport import ClientConfig, SRPCTransport, slimrpc_channel_factory
from slima2a.handler import SRPCHandler
from slima2a.types.v1.a2a_pb2_slimrpc import add_A2AServiceServicer_to_server

from .display import B, GR, R, YL, RD, SEP, log
from .results import MeshResult

SLIM_URL = "http://localhost:46357"
SLIM_SECRET = "secretsecretsecretsecretsecretsecret"
SLIM_NS = "bench"
SLIM_GROUP = "mesh"

# Time (s) for SLIM subscription to route before signalling ready.
SERVER_SETTLE = 6.0
# Extra settle after all servers are up before clients start sending.
ROUTE_SETTLE = 1.5


def _agent_name(idx: int) -> str:
    return f"agent-{idx}"


def _slim_name(idx: int) -> slim_bindings.Name:
    return slim_bindings.Name(SLIM_NS, SLIM_GROUP, _agent_name(idx))


def _slim_url_str(idx: int) -> str:
    """URL string used by slimrpc_channel_factory — must be 'ns/group/name'."""
    return f"{SLIM_NS}/{SLIM_GROUP}/{_agent_name(idx)}"


def _make_proto_card(idx: int) -> ProtoAgentCard:
    """Build the protobuf AgentCard advertising slimrpc for agent-{idx}."""
    card = ProtoAgentCard()
    card.name = _agent_name(idx)
    card.description = f"echo agent {idx}"
    card.version = "0.1.0"
    card.default_input_modes.append("text")
    card.default_output_modes.append("text")
    card.capabilities.streaming = True
    iface = card.supported_interfaces.add()
    iface.url = _slim_url_str(idx)
    iface.protocol_binding = "slimrpc"
    return card


class _EchoExecutor(AgentExecutor):
    """Echoes the first text part of the incoming message back as an artifact."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        msg = context.message
        # Find the first text part to echo; fall back to empty string.
        text = ""
        if msg and msg.parts:
            part = msg.parts[0]
            which = part.WhichOneof("content")
            if which == "text":
                text = part.text
            elif which == "raw":
                text = part.raw.decode(errors="replace")

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.submit()
        await updater.start_work()
        echo_part = Part()
        echo_part.text = text
        await updater.add_artifact([echo_part], name="result")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()


def _build_request(payload_text: str) -> SendMessageRequest:
    req = SendMessageRequest()
    req.message.message_id = str(uuid.uuid4())
    req.message.role = Role.ROLE_USER
    part = req.message.parts.add()
    part.text = payload_text
    return req


async def _one_request(client, request: SendMessageRequest) -> float:
    """Send one A2A round trip and return elapsed ms."""
    t0 = time.perf_counter()
    # Client.send_message is an AsyncIterator of (StreamResponse, Task | None)
    async for _event, _task in client.send_message(request):
        pass
    return (time.perf_counter() - t0) * 1000.0


async def _agent_main(
    idx: int,
    n: int,
    rounds: int,
    payload_bytes: int,
    fanout_concurrent: bool,
    ready: mp.Barrier,   # type: ignore[type-arg]
    go: mp.Barrier,       # type: ignore[type-arg]
    done: mp.Barrier,     # type: ignore[type-arg]
    out_q: mp.Queue,      # type: ignore[type-arg]
) -> None:
    loop = asyncio.get_running_loop()
    payload_text = "x" * payload_bytes
    peers = [j for j in range(n) if j != idx]

    # 1. Init SLIM — uniffi_set_event_loop is called inside initialize_slim_service
    service = await initialize_slim_service(log_level="error")
    local_name = _slim_name(idx)
    local_app, conn_id = await connect_and_subscribe(
        service, local_name, slim_url=SLIM_URL, secret=SLIM_SECRET
    )

    # 2. Start echo A2A server over SlimRPC
    handler = DefaultRequestHandler(
        agent_executor=_EchoExecutor(),
        task_store=InMemoryTaskStore(),
    )
    srpc_handler = SRPCHandler(
        agent_card=_make_proto_card(idx),
        request_handler=handler,
    )
    server = slim_bindings.Server.new_with_connection(local_app, local_name, conn_id)
    add_A2AServiceServicer_to_server(srpc_handler, server)
    server_task = asyncio.create_task(server.serve_async())

    # Wait for SLIM subscription to propagate before signalling ready
    await asyncio.sleep(SERVER_SETTLE)

    # 3. Signal this agent's server is up
    await loop.run_in_executor(None, ready.wait)
    # Extra settle so all peer subscriptions are fully routed
    await asyncio.sleep(ROUTE_SETTLE)

    # 4. Build per-peer A2A clients
    ch_factory = slimrpc_channel_factory(local_app, conn_id)
    client_cfg = ClientConfig(
        slimrpc_channel_factory=ch_factory,
        accepted_output_modes=["text"],
        supported_protocol_bindings=["slimrpc"],
    )
    factory = ClientFactory(client_cfg)
    factory.register("slimrpc", SRPCTransport.create)
    peer_clients = {j: factory.create(_make_proto_card(j)) for j in peers}

    # 5. All agents clients ready — fire!
    await loop.run_in_executor(None, go.wait)

    # 6. Measure round trips (timer excludes setup)
    samples: list[float] = []
    completed = 0
    for _ in range(rounds):
        if fanout_concurrent:
            requests = [_build_request(payload_text) for _ in peers]
            results = await asyncio.gather(
                *(_one_request(peer_clients[j], req) for j, req in zip(peers, requests)),
                return_exceptions=True,
            )
            for r in results:
                if isinstance(r, float):
                    samples.append(r)
                    completed += 1
        else:
            for j in peers:
                try:
                    samples.append(await _one_request(peer_clients[j], _build_request(payload_text)))
                    completed += 1
                except Exception as exc:
                    log(RD, f"agent-{idx}", f"send to agent-{j} failed: {exc}")

    # 7. All done — collect results
    await loop.run_in_executor(None, done.wait)
    out_q.put((idx, samples, completed))

    server_task.cancel()
    try:
        await asyncio.wait_for(server_task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass


def _agent_proc(
    idx: int,
    n: int,
    rounds: int,
    payload_bytes: int,
    fanout_concurrent: bool,
    ready: mp.Barrier,   # type: ignore[type-arg]
    go: mp.Barrier,       # type: ignore[type-arg]
    done: mp.Barrier,     # type: ignore[type-arg]
    out_q: mp.Queue,      # type: ignore[type-arg]
) -> None:
    asyncio.run(
        _agent_main(idx, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q)
    )


def run_a2a_slim_mesh(
    n: int,
    payload_bytes: int,
    rounds: int,
    fanout_concurrent: bool,
) -> MeshResult:
    ctx = mp.get_context("spawn")
    ready: mp.Barrier = ctx.Barrier(n)   # type: ignore[attr-defined]
    go:    mp.Barrier = ctx.Barrier(n)   # type: ignore[attr-defined]
    done:  mp.Barrier = ctx.Barrier(n)   # type: ignore[attr-defined]
    out_q: mp.Queue   = ctx.Queue()      # type: ignore[attr-defined]

    expected = n * (n - 1) * rounds
    fanout = "concurrent" if fanout_concurrent else "sequential"
    cores = mp.cpu_count()

    log(YL, "A2A-SLIM",
        f"Process-per-agent, {B}{fanout}{R} fan-out: "
        f"{B}{n}{R} procs on {B}{cores}{R} cores, "
        f"{B}{n}x{n-1}{R} edges x {B}{rounds}{R} round(s) = {B}{expected}{R} A2A round trips")
    log(YL, "A2A-SLIM",
        f"stack: slima2a==0.6.0 / slim-bindings==1.4.1 / "
        f"a2a-sdk==1.0.0-alpha.0 / SLIM node: {SLIM_URL} (ghcr.io/agntcy/slim:1.4.0)")

    print(SEP)
    t0 = time.perf_counter()
    procs = [
        ctx.Process(
            target=_agent_proc,
            args=(i, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()

    collected: dict[int, tuple[list[float], int]] = {}
    while len(collected) < n:
        agent_idx, samps, completed_count = out_q.get()
        collected[agent_idx] = (samps, completed_count)
    for p in procs:
        p.join()
    wall = (time.perf_counter() - t0) * 1000.0

    all_samples: list[float] = []
    total_completed = 0
    for i in range(n):
        s, c = collected[i]
        all_samples.extend(s)
        total_completed += c

    delivery_pct = 100.0 * total_completed / expected if expected else 0.0
    ok = total_completed == expected
    status_color = GR if ok else RD
    log(status_color, "A2A-SLIM",
        f"done in {wall:.1f} ms — "
        f"{len(all_samples)} trips measured, "
        f"{total_completed}/{expected} delivered ({delivery_pct:.1f}%) "
        f"{'PASS' if ok else 'FAIL'}")

    return MeshResult(
        name=f"full_mesh_a2a_over_slim_{fanout}",
        samples=all_samples,
        metadata={
            "transport": "a2a_over_slim",
            "package": "slima2a==0.6.0",
            "slim_bindings": "1.4.1",
            "slim_node": "ghcr.io/agntcy/slim:1.4.0",
            "mode": fanout,
            "agents": n,
            "rounds": rounds,
            "cpu_cores": cores,
            "directed_edges": n * (n - 1),
            "expected_messages": expected,
            "requests_completed": total_completed,
            "delivery_pct": round(delivery_pct, 2),
            "payload_bytes": payload_bytes,
            "wall_ms": round(wall, 1),
        },
    )
