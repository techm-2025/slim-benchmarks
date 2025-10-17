"""A2A Multi-Agent Latency Testing"""
import asyncio
import time
import random
from datetime import datetime
import pandas as pd
from agent import start_agent
from client import send_message

random.seed()

async def main():
    # Config
    NUM_AGENTS = 10
    MESSAGES_PER_SENDER = 100
    BASE_PORT = 8000
    
    # 1. Start agents (agent i runs on port BASE_PORT + i)
    print(f"Starting {NUM_AGENTS} agents...")
    servers = []
    for i in range(NUM_AGENTS):
        server = await start_agent(agent_id=i, port=BASE_PORT + i)
        servers.append(server)
    
    await asyncio.sleep(2)
    print(f"Running on ports {BASE_PORT} to {BASE_PORT + NUM_AGENTS - 1}\n")
    
    # 2. Randomly assign senders/receivers
    num_senders = random.randint(1, NUM_AGENTS - 1)
    sender_ids = random.sample(range(NUM_AGENTS), num_senders)
    receiver_ids = [i for i in range(NUM_AGENTS) if i not in sender_ids]
    
    print(f"Senders ({len(sender_ids)}): {sender_ids}")
    print(f"Receivers ({len(receiver_ids)}): {receiver_ids}")
    print(f"Total messages: {len(sender_ids) * MESSAGES_PER_SENDER}\n")
    
    # 3. Send messages and measure latency
    print("Sending messages...")
    tasks = []
    for sender_id in sender_ids:
        for msg_num in range(MESSAGES_PER_SENDER):
            receiver_id = random.choice(receiver_ids)
            sender_port = BASE_PORT + sender_id
            receiver_port = BASE_PORT + receiver_id
            tasks.append(send_message(sender_id, receiver_id, sender_port, receiver_port, msg_num))
    
    start_time = time.time()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.time() - start_time
    
    # Filter successful results
    results = [r for r in results if r and not isinstance(r, Exception)]
    print(f"Completed in {elapsed:.2f}s ({len(results)}/{len(tasks)} successful)\n")
    
    # 4. Compute statistics
    df = pd.DataFrame(results)
    
    print("LATENCY STATISTICS")
    print(f"Messages:  {len(df)}")
    print(f"Mean:      {df['latency_ms'].mean():.2f} ms")
    print(f"Median:    {df['latency_ms'].median():.2f} ms")
    print(f"Std Dev:   {df['latency_ms'].std():.2f} ms")
    print(f"Min:       {df['latency_ms'].min():.2f} ms")
    print(f"Max:       {df['latency_ms'].max():.2f} ms")
    print(f"P50:       {df['latency_ms'].quantile(0.50):.2f} ms")
    print(f"P90:       {df['latency_ms'].quantile(0.90):.2f} ms")
    print(f"P95:       {df['latency_ms'].quantile(0.95):.2f} ms")
    print(f"P99:       {df['latency_ms'].quantile(0.99):.2f} ms")
    
    # 5. Export to Excel
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"latency_report_{timestamp}.xlsx"
    
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        # Overall stats
        overall = pd.DataFrame([{
            'total_messages': len(df),
            'mean_ms': df['latency_ms'].mean(),
            'median_ms': df['latency_ms'].median(),
            'std_ms': df['latency_ms'].std(),
            'min_ms': df['latency_ms'].min(),
            'max_ms': df['latency_ms'].max(),
            'p50_ms': df['latency_ms'].quantile(0.50),
            'p90_ms': df['latency_ms'].quantile(0.90),
            'p95_ms': df['latency_ms'].quantile(0.95),
            'p99_ms': df['latency_ms'].quantile(0.99),
        }])
        overall.to_excel(writer, sheet_name='Overall', index=False)
        
        # All messages
        df.to_excel(writer, sheet_name='Messages', index=False)
        
        # Per-sender stats
        sender_stats = df.groupby('sender_id')['latency_ms'].agg([
            'count', 'mean', 'median', 'std', 'min', 'max'
        ]).round(2)
        sender_stats.to_excel(writer, sheet_name='Senders')
        
        # Per-receiver stats
        receiver_stats = df.groupby('receiver_id')['latency_ms'].agg([
            'count', 'mean', 'median', 'std', 'min', 'max'
        ]).round(2)
        receiver_stats.to_excel(writer, sheet_name='Receivers')
    
    print(f"✓ Excel report saved: {filename}\n")
    
    # 6. Shutdown
    print("Shutting down agents...")
    for server in servers:
        server.should_exit = True
    await asyncio.sleep(0.5)
    print("Done!!\n")


if __name__ == "__main__":
    asyncio.run(main())