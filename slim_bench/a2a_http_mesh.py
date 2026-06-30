"""A2A full mesh, no SLIM (cell 1): A2A over plain HTTP, process per agent.

Each agent is its own process running an A2A HTTP server (A2AStarletteApplication
with an echo executor, served by uvicorn) plus an A2A HTTP client that resolves
each peer's agent card and sends a message, awaiting the result. A measured unit
is one A2A request to completion (round trip), directly comparable to cell 2
(A2A over SLIM).

Needs the agntcy/a2a stack (.venv-a2a) but no SLIM node — pure HTTP on loopback.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import time
from uuid import uuid4

import httpx
import uvicorn
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.server.apps import A2AStarletteApplication
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities, AgentCard, AgentSkill, DataPart, Message, Part, Role,
    UnsupportedOperationError,
)
from a2a.utils.errors import ServerError

from .display import B, GR, R, YL, log
from .results import MeshResult

HTTP_HOST = "127.0.0.1"
BASE_PORT = 9300
SERVER_SETTLE = 1.5  # seconds for uvicorn to come up before clients resolve cards


class _EchoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        data = next(
            p.root.data for p in context.message.parts if isinstance(p.root, DataPart)
        )
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.submit()
        await updater.start_work()
        await updater.add_artifact([Part(root=DataPart(data=data))], name="result")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise ServerError(error=UnsupportedOperationError())


def _echo_card(idx: int) -> AgentCard:
    port = BASE_PORT + idx
    return AgentCard(
        name=f"agent-{idx}", description="echo", url=f"http://{HTTP_HOST}:{port}/",
        version="0.1.0", default_input_modes=["text"], default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[AgentSkill(id="echo", name="echo", description="echo", tags=["echo"], examples=[])],
    )


async def _one_request(client, data: dict) -> float:
    message = Message(message_id=str(uuid4()), role=Role.user, parts=[Part(root=DataPart(data=data))])
    t0 = time.perf_counter()
    saw_event = False
    async for _event in client.send_message(message):
        saw_event = True
    if not saw_event:
        raise RuntimeError("no response")
    return (time.perf_counter() - t0) * 1000.0


async def _agent_main(idx, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q) -> None:
    loop = asyncio.get_running_loop()
    data = {"p": "x" * payload_bytes}
    peers = [j for j in range(n) if j != idx]

    handler = DefaultRequestHandler(agent_executor=_EchoExecutor(), task_store=InMemoryTaskStore())
    app = A2AStarletteApplication(agent_card=_echo_card(idx), http_handler=handler).build()
    config = uvicorn.Config(app, host=HTTP_HOST, port=BASE_PORT + idx, log_level="error")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    await asyncio.sleep(SERVER_SETTLE)

    httpx_client = httpx.AsyncClient(timeout=30.0)
    peer_clients = {}
    for j in peers:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=f"http://{HTTP_HOST}:{BASE_PORT + j}/")
        card = await resolver.get_agent_card()
        factory = ClientFactory(ClientConfig(httpx_client=httpx_client, accepted_output_modes=["text"]))
        peer_clients[j] = factory.create(card)

    await loop.run_in_executor(None, ready.wait)
    await loop.run_in_executor(None, go.wait)

    samples: list[float] = []
    completed = 0
    for _ in range(rounds):
        if fanout_concurrent:
            results = await asyncio.gather(
                *(_one_request(peer_clients[j], data) for j in peers), return_exceptions=True
            )
            for r in results:
                if isinstance(r, float):
                    samples.append(r); completed += 1
        else:
            for j in peers:
                try:
                    samples.append(await _one_request(peer_clients[j], data)); completed += 1
                except Exception:
                    pass

    await loop.run_in_executor(None, done.wait)
    await httpx_client.aclose()
    out_q.put((idx, samples, completed))
    server.should_exit = True  # let uvicorn shut down cleanly (no cancel noise)
    try:
        await asyncio.wait_for(server_task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass


def _agent_proc(idx, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q) -> None:
    asyncio.run(_agent_main(idx, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q))


def run_a2a_http_mesh(n: int, payload_bytes: int, rounds: int, fanout_concurrent: bool) -> MeshResult:
    ctx = mp.get_context("spawn")
    ready = ctx.Barrier(n)
    go = ctx.Barrier(n)
    done = ctx.Barrier(n)
    out_q: mp.Queue = ctx.Queue()

    expected = n * (n - 1) * rounds
    fanout = "concurrent" if fanout_concurrent else "sequential"
    cores = mp.cpu_count()
    log(YL, "A2A-HTTP",
        f"Process-per-agent, {B}{fanout}{R} fan-out: {B}{n}{R} procs on {B}{cores}{R} cores, "
        f"{B}{n}x{n-1}{R} edges x {B}{rounds}{R} round(s) = {B}{expected}{R} A2A round trips")

    t0 = time.perf_counter()
    procs = [
        ctx.Process(target=_agent_proc,
                    args=(i, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q))
        for i in range(n)
    ]
    for p in procs:
        p.start()

    collected: dict[int, tuple[list[float], int]] = {}
    while len(collected) < n:
        idx, samples, completed = out_q.get()
        collected[idx] = (samples, completed)
    for p in procs:
        p.join()
    wall = (time.perf_counter() - t0) * 1000.0

    all_samples: list[float] = []
    total_completed = 0
    for idx in range(n):
        s, c = collected[idx]
        all_samples.extend(s)
        total_completed += c

    log(GR, "A2A-HTTP", f"done in {wall:.1f} ms — {len(all_samples)} round trips, {total_completed} completed")

    return MeshResult(
        name=f"full_mesh_a2a_no_slim_{fanout}",
        samples=all_samples,
        metadata={
            "transport": "a2a_no_slim",
            "mode": fanout,
            "agents": n,
            "rounds": rounds,
            "cpu_cores": cores,
            "directed_edges": n * (n - 1),
            "expected_messages": expected,
            "requests_completed": total_completed,
            "payload_bytes": payload_bytes,
            "wall_ms": round(wall, 1),
        },
    )
