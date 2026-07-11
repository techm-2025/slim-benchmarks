"""A2A Client"""
import time
import uuid
import httpx
from a2a.types import Message, TextPart


# Single shared client for all requests
client = httpx.AsyncClient(
    timeout=30.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)


async def send_message(sender_id: int, receiver_id: int, sender_port: int, receiver_port: int, msg_num: int):
    """Send a message and measure latency"""
    try:
        # Create A2A message
        message = Message(
            messageId=str(uuid.uuid4()),
            role="user",
            parts=[TextPart(
                type="text",
                text=f"Message {msg_num} from Agent-{sender_id}"
            )]
        )
        
        # JSON-RPC 2.0 request
        request = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": message.model_dump(mode='json'),
                "metadata": {}
            },
            "id": str(uuid.uuid4())
        }
        
        # Send to receiver's port
        url = f"http://localhost:{receiver_port}/"
        
        t0 = time.perf_counter()
        response = await client.post(url, json=request)
        t1 = time.perf_counter()
        
        response.raise_for_status()
        latency_ms = (t1 - t0) * 1000
        
        return {
            'sender_id': sender_id,
            'receiver_id': receiver_id,
            'sender_port': sender_port,
            'receiver_port': receiver_port,
            'message_num': msg_num,
            'latency_ms': round(latency_ms, 3)
        }
        
    except Exception:
        return None
