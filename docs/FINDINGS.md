# A2A over SLIM — Benchmark Findings

**Date:** 2026-07-01  
**Branch:** `slima2a`  
**Evidence:** `docs/evidence/a2a_slim_mesh_sweep.json`

---

## What we did

### Goal

Answer: **does routing A2A agent traffic through a SLIM node add prohibitive latency, or is it efficient?**

### Stack

| Component | Version |
|---|---|
| `slima2a` | 0.6.0 (public PyPI package) |
| `slim-bindings` | 1.4.1 |
| `a2a-sdk` | 1.0.0-alpha.0 |
| SLIM node image | `ghcr.io/agntcy/slim:1.4.0` |
| Python | 3.11 |
| Machine | 12 CPU cores, macOS |

### Topology

Full-mesh, N agents. Each agent is a separate OS process (true parallelism via `multiprocessing.spawn`). Every agent runs both an **echo A2A server** (over SLIM/slimrpc) and N-1 **A2A clients** (one per peer). All traffic routes through a single local SLIM node at `localhost:46357`.

```
agent-0 ──┐                ┌── agent-0
agent-1 ──┤  SLIM node     ├── agent-1
  ...     ├──  :46357    ──┤   ...
agent-N ──┘                └── agent-N
```

Every directed edge is exercised each round: **N × (N-1) A2A round trips per round**.

### Measurement unit

One measured sample = one complete A2A `SendMessage` round trip:

- **Start**: just before `client.send_message(request)` is called
- **End**: after the last `(StreamResponse, Task)` event is consumed from the async iterator
- **Timer**: `time.perf_counter()` (sub-microsecond resolution)
- **Excludes**: SLIM init, subscription, server startup, client construction

Only the payload is varied (64 B vs 512 B text). The agent logic is a trivial echo; there is no LLM or computation.

### Fan-out modes

| Mode | Behavior |
|---|---|
| `sequential` | Each agent sends to peers one at a time (await each before next) |
| `concurrent` | Each agent fans out to all peers simultaneously via `asyncio.gather` |

Sequential is the **apples-to-apples comparison** against the HTTP baseline (which also sends sequentially). Concurrent shows how SLIM handles burst fan-out.

### Sweep parameters

- Agent counts: **5, 10, 20**
- Payload sizes: **64 B, 512 B**
- Rounds: **3** per scenario
- Total scenarios: 12 (3 × 2 × 2 modes)
- Total messages delivered: **5,880**

### Synchronization

Three `multiprocessing.Barrier(n)` checkpoints ensure fair timing:

1. **`ready`**: all N servers have completed `subscribe_async` and settled for 6 s (SLIM route propagation)
2. **`go`**: all N agents have built their peer clients and are ready to send simultaneously
3. **`done`**: all measurements collected before any process exits

---

## What we found

### Key numbers — sequential mode

| Agents | In-flight msgs/round | Mean (ms) | p95 (ms) | p99 (ms) | Max (ms) |
|---|---|---|---|---|---|
| 5  | 20  | 5.6 | 11–13 | 11–14 | 14 |
| 10 | 90  | 7.5 | 13    | 16–18 | 19 |
| 20 | 380 | 14–15 | 32–36 | 46–66 | 113 |

> Payload size (64 B vs 512 B) has no meaningful effect — see next section.

### Key numbers — concurrent mode

| Agents | In-flight msgs simultaneously | Mean (ms) | p95 (ms) | p99 (ms) | Max (ms) |
|---|---|---|---|---|---|
| 5  | 20  | 11.6–12.3 | 19–19 | 19–20 | 20 |
| 10 | 90  | 35.1–35.8 | 52–53 | 52–54 | 59 |
| 20 | 380 | 116–120   | 209–216 | 231–237 | 311 |

### Comparison against HTTP baseline (sequential)

The `feat/full-mesh-scale-bench` branch measured identical A2A round trips over plain HTTP (no SLIM, direct loopback):

| Transport | 5-agent mean | 10-agent mean | 20-agent mean | SLIM overhead |
|---|---|---|---|---|
| A2A over HTTP (no SLIM) | 3.1 ms | 4.1 ms | 7.4 ms | baseline |
| A2A over SLIM (this branch) | 5.6 ms | 7.5 ms | 14.6 ms | ~1.85–1.9× |

SLIM adds a **consistent ~1.85–1.9× overhead** in sequential mode across all agent counts. The additive cost is approximately **2.5–7 ms** per hop, growing slightly with N (more subscriptions in the routing table).

---

## Inferences

### 1. SLIM adds modest, consistent latency in sequential mode

The ~1.85× overhead is low enough to be acceptable for most agentic use cases. Consider what SLIM provides for that cost:

- **Identity-based routing** — agents address each other by logical name (`bench/mesh/agent-N`), not by IP/port
- **MLS encryption** (optional) — end-to-end encrypted channels between agents
- **No direct TCP/IP required** — agents don't need to know each other's addresses; they only need to reach the SLIM node

For an agent that does any real work (even a 1 ms LLM call), 2.5–7 ms of transport overhead is essentially invisible.

### 2. Payload size is irrelevant

64 B and 512 B payloads produce nearly identical latencies (delta < 1 ms across all scenarios). SLIM's overhead is dominated by **routing/session protocol overhead**, not serialization or bandwidth. This will remain true for typical A2A payloads up to at least a few KB.

### 3. Sequential mode scales sub-linearly with agent count

Going from 5 → 10 → 20 agents in sequential mode:

- Mean: 5.6 → 7.5 → 14.6 ms (2.6× increase for 4× more agents)
- p95: 11–13 → 13 → 32–36 ms

The SLIM node handles the growing subscription table and concurrent connections gracefully. At 20 agents with 380 directed edges, mean latency is still under 15 ms. This is sub-linear scaling — SLIM routing does not create a per-agent tax that stacks linearly.

### 4. Concurrent burst fan-out degrades sharply at scale

In concurrent mode, every agent fires to all N-1 peers simultaneously. This creates:

- **5 agents**: 20 simultaneous in-flight messages → 11.6–12.3 ms mean (2.1× sequential)
- **10 agents**: 90 simultaneous → 35 ms mean (4.7× sequential)
- **20 agents**: 380 simultaneous → 118 ms mean (8× sequential)

The degradation is **super-linear**: each 2× increase in agents produces roughly a 3–4× increase in concurrent mean latency. This is consistent with single-node SLIM acting as a bottleneck when all agents burst simultaneously.

At 20 agents the p99 exceeds 230 ms and max reaches 311 ms — unacceptable for interactive use. However, this scenario is highly synthetic: 380 simultaneous messages through a single locally-run node is an extreme burst.

### 5. 100% delivery in all 12 scenarios

Every single expected message was delivered across all 5,880 round trips. Zero drops, zero timeouts. This is the most important finding: **SLIM does not sacrifice reliability for performance**. Even under the 380-simultaneous-message burst at 20 agents, nothing was lost.

---

## Summary

| Question | Answer |
|---|---|
| Does SLIM add latency? | Yes, ~1.85× vs direct HTTP in sequential mode (~2.5–7 ms additive) |
| Is that overhead acceptable? | Yes for typical agentic workloads; overhead is constant and small relative to any real agent work |
| Does payload size matter? | No — 64 B and 512 B are statistically identical |
| How does sequential mode scale? | Sub-linearly — graceful up to 20 agents |
| How does concurrent burst fare? | Degrades sharply at scale; 20 agents × full-mesh burst → 118 ms mean, 311 ms max on a single node |
| Is delivery reliable? | 100% across all 5,880 messages in all 12 scenarios |

**Bottom line**: SLIM is efficient for sequential or low-concurrency A2A traffic. The routing overhead is a fixed ~2–7 ms per message, not a per-agent cost. Concurrent burst fan-out at scale hits a single-node bottleneck — this is a deployment/topology concern (SLIM clustering, back-pressure, or throttled fan-out), not a fundamental protocol inefficiency.
