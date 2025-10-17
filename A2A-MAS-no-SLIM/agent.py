"""A2A Agent Server"""
import asyncio
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import AgentCard, AgentSkill, Message, TextPart, AgentCapabilities


class EchoAgent(AgentExecutor):
    """Simple echo agent"""
    
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Get incoming message
        incoming = context.message

        # Extract text properly
        if incoming.parts:
            part = incoming.parts[0]
            # part dict/object
            if hasattr(part, 'text'):
                text = part.text
            elif isinstance(part, dict):
                text = part.get('text', 'empty')
            else:
                text = str(part)
        else:
            text = "empty"
        
        # Create response
        response = Message(
            messageId=f"resp-{incoming.message_id}",
            role="agent",
            parts=[TextPart(type="text", text=f"Echo: {text}")]
        )
        
        # Send it back
        await event_queue.enqueue_event(response)
    
    async def cancel(self, task_id: str, context_id: str | None) -> None:
        """ cancel task - not used in echo agent """
        pass


async def start_agent(agent_id: int, port: int):
    """Start A2A agent server"""
    
    # Agent card
    card = AgentCard(
        name=f'Agent-{agent_id}',
        description=f'Echo agent {agent_id}',
        url=f'http://localhost:{port}/',
        version='1.0.0',
        defaultInputModes=['text'],
        defaultOutputModes=['text'],
        skills=[AgentSkill(
            id=f'echo_{agent_id}',
            name='Echo',
            description='Echoes back messages',
            tags=['echo', 'test'],
            examples=['hello', 'test']
        )],
        capabilities=AgentCapabilities()
    )
    
    # Request handler
    handler = DefaultRequestHandler(
        agent_executor=EchoAgent(),
        task_store=InMemoryTaskStore()
    )
    
    # Starlette app
    app = A2AStarletteApplication(
        agent_card=card,
        http_handler=handler
    )
    
    # Start server
    config = uvicorn.Config(
        app=app.build(),
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False
    )
    
    server = uvicorn.Server(config)
    asyncio.create_task(server.serve())
    
    return server