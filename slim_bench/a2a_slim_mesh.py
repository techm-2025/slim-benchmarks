"""A2A-over-SLIM full mesh (cell 2), process per agent.

Each agent is its own process running an echo AetherA2AServer (identity
agent-i) plus an AetherA2AClient that sends an A2A message to every peer and
awaits the result. One SLIM identity per process: the client reuses the
server's SLIM connection, so a process talks to its peers but never to itself.

A measured unit is one A2A request to completion (submit -> result artifact),
i.e. a full round trip, comparable to the HTTP legs. Agents always run as
separate OS processes (true parallelism); the per-agent fan-out to peers is
either sequential (await each) or concurrent (asyncio.gather).

Requires the agntcy A2A stack (.venv-a2a) and a slim:1.0.0 node with the Aether
server config.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities, AgentCard, AgentSkill, DataPart, Part, UnsupportedOperationError,
)
from a2a.utils.errors import ServerError

from aether_agents.common.a2a import (
    AetherA2AServer, AetherA2AClient, SLIMConfig, task_final_result,
)

from .display import B, GR, R, YL, log
from .results import MeshResult

SERVER_SETTLE = 6.0   # seconds for the SLIM server session to bind
ROUTE_SETTLE = 1.5    # seconds after all servers up before clients send


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


def _echo_card(name: str) -> AgentCard:
    return AgentCard(
        name=name, description="echo", url="http://localhost/", version="0.1.0",
        default_input_modes=["text"], default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[AgentSkill(id="echo", name="echo", description="echo", tags=["echo"], examples=[])],
    )


async def _one_request(client: AetherA2AClient, peer: str, data: dict) -> float:
    t0 = time.perf_counter()
    task = None
    async for updated_task, _event in client.send_message(peer, data):
        task = updated_task
    task_final_result(task)  # raises if the task failed
    return (time.perf_counter() - t0) * 1000.0


async def _agent_main(idx, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q) -> None:
    loop = asyncio.get_running_loop()
    data = {"p": "x" * payload_bytes}
    peers = [f"agent-{j}" for j in range(n) if j != idx]

    server = AetherA2AServer(
        agent_card=_echo_card(f"agent-{idx}"),
        agent_executor=_EchoExecutor(),
        slim_config=SLIMConfig(identity=f"agent-{idx}"),
    )
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(SERVER_SETTLE)

    client = AetherA2AClient(slim_config=SLIMConfig(identity=f"agent-{idx}"))

    await loop.run_in_executor(None, ready.wait)
    await asyncio.sleep(ROUTE_SETTLE)
    await loop.run_in_executor(None, go.wait)

    samples: list[float] = []
    completed = 0
    for _ in range(rounds):
        if fanout_concurrent:
            results = await asyncio.gather(
                *(_one_request(client, p, data) for p in peers), return_exceptions=True
            )
            for r in results:
                if isinstance(r, float):
                    samples.append(r); completed += 1
        else:
            for p in peers:
                try:
                    samples.append(await _one_request(client, p, data)); completed += 1
                except Exception:
                    pass

    await loop.run_in_executor(None, done.wait)
    out_q.put((idx, samples, completed))
    server_task.cancel()


def _agent_proc(idx, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q) -> None:
    asyncio.run(_agent_main(idx, n, rounds, payload_bytes, fanout_concurrent, ready, go, done, out_q))


def run_a2a_slim_mesh(n: int, payload_bytes: int, rounds: int, fanout_concurrent: bool) -> MeshResult:
    ctx = mp.get_context("spawn")
    ready = ctx.Barrier(n)
    go = ctx.Barrier(n)
    done = ctx.Barrier(n)
    out_q: mp.Queue = ctx.Queue()

    expected = n * (n - 1) * rounds
    fanout = "concurrent" if fanout_concurrent else "sequential"
    cores = mp.cpu_count()
    log(YL, "A2A-SLIM",
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

    log(GR, "A2A-SLIM", f"done in {wall:.1f} ms — {len(all_samples)} round trips, {total_completed} completed")

    return MeshResult(
        name=f"full_mesh_a2a_over_slim_{fanout}",
        samples=all_samples,
        metadata={
            "transport": "a2a_over_slim",
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
