"""Echo A2A server process (over SLIM unicast). Runs until killed."""
import asyncio
import sys

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities, AgentCard, AgentSkill, DataPart, Part, UnsupportedOperationError,
)
from a2a.utils.errors import ServerError

from aether_agents.common.a2a import AetherA2AServer, SLIMConfig


class EchoExecutor(AgentExecutor):
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


def echo_card(name: str) -> AgentCard:
    return AgentCard(
        name=name, description="echo", url="http://localhost/", version="0.1.0",
        default_input_modes=["text"], default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[AgentSkill(id="echo", name="echo", description="echo", tags=["echo"], examples=[])],
    )


async def main(identity: str) -> None:
    server = AetherA2AServer(
        agent_card=echo_card(identity),
        agent_executor=EchoExecutor(),
        slim_config=SLIMConfig(identity=identity),
    )
    print(f"server {identity} starting", flush=True)
    await server.start()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "echo-agent"))
