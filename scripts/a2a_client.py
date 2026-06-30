"""A2A client process: send one message to the echo server, print the result."""
import asyncio
import sys

from aether_agents.common.a2a import AetherA2AClient, SLIMConfig, task_final_result


async def main(target: str) -> None:
    client = AetherA2AClient(slim_config=SLIMConfig(identity="bench-client"))
    task = None
    async for updated_task, _event in client.send_message(target, {"ping": "hello"}):
        task = updated_task
    print("RESULT:", task_final_result(task), flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "echo-agent"))
