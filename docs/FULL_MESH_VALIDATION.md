# Full-Mesh SLIM Validation (step 1)

Purpose: stand up a real SLIM full mesh and confirm the broker setup works at the
target agent count before designing the full transport-comparison sweep. This is
the validation step only — one transport (SLIM unicast), no HTTP / A2A-over-SLIM
comparison yet.

## Why this exists

The earlier benchmark on `albertid1` (`A2A-MAS-no-SLIM/demo_benchmark.py`) measured
an in-memory `InMemorySlimBus` — `await asyncio.sleep(0)` then return. That is not
SLIM; it measures an async hop against a real HTTP socket. The "SLIM 0.08 ms vs
HTTP 2.4 ms" headline from that run is not a transport comparison.

This harness uses the real `slim-bindings==1.3.0` client against a live SLIM node
(the same client and node config carried over from `develop-slim1.x`).

## Topology

- N agents, each a real SLIM app (`create_app_with_secret`, `subscribe`).
- Each agent runs a receiver loop (`listen_for_session` -> per-session `get_message`).
- Full mesh: every agent holds a `POINT_TO_POINT` session to every other agent.
  Sessions are established once in a warm phase (setup cost reported separately),
  then each agent publishes one message per peer per round. N x (N-1) directed edges.
- Metric: per-message `publish_and_wait` latency (delivery confirmed by the broker).

Two execution modes:

- **sequential** — one publish in flight at a time. Clean per-message latency floor.
- **concurrent** — every agent fans out to all peers at once (one thread per source,
  released together on a barrier). Measures behaviour under congestion, which is the
  property that matters for SLIM at scale.

Delivery is verified, not assumed: the runner reports `messages_received_by_peers`
(summed `get_message` count across all agents) and it matches the send count in every
config below.

## How to run

```bash
# 1. SLIM node
docker run --rm -d --name slim-node -p 46357:46357 \
  -v "$(pwd)/server-config.yaml:/config.yaml" \
  --entrypoint /slim ghcr.io/agntcy/slim:1.3.0 --config /config.yaml

# 2. venv (slim-bindings resolves on Python 3.12)
uv venv .venv-mesh --python python3
uv pip install --python .venv-mesh/bin/python slim-bindings==1.3.0

# 3a. single run
PYTHONPATH=. .venv-mesh/bin/python mesh_benchmark.py \
  --agents 20 --rounds 5 --payload-size 64 --concurrent

# 3b. sweep (agent counts x payload sizes x both modes)
PYTHONPATH=. .venv-mesh/bin/python mesh_benchmark.py --sweep \
  --agents-list 10,20,40 --payloads 64,512,4096 --rounds 5 \
  --output docs/evidence/full_mesh_sweep.json
```

## Results (local, 2026-06-22, SLIM node ghcr.io/agntcy/slim:1.3.0, 5 rounds/config)

Per-message publish latency in ms. Every config delivered 100% (received == sent).
Full raw data in `docs/evidence/full_mesh_sweep.json`.

### Sequential (one publish in flight)

| Agents | Payload | Messages | mean | p95 | p99 | round wall ms |
|---|---|---|---|---|---|---|
| 10 | 64   | 450  | 0.055 | 0.099 | 0.117 | 5.0   |
| 10 | 512  | 450  | 0.084 | 0.126 | 0.185 | 7.6   |
| 10 | 4096 | 450  | 0.329 | 0.366 | 0.439 | 29.7  |
| 20 | 64   | 1900 | 0.057 | 0.102 | 0.138 | 21.8  |
| 20 | 512  | 1900 | 0.103 | 0.187 | 0.267 | 39.3  |
| 20 | 4096 | 1900 | 0.335 | 0.402 | 0.551 | 127.5 |
| 40 | 64   | 7800 | 0.080 | 0.157 | 0.216 | 124.9 |
| 40 | 512  | 7800 | 0.102 | 0.164 | 0.206 | 160.2 |
| 40 | 4096 | 7800 | 0.348 | 0.413 | 0.492 | 544.0 |

### Concurrent (every agent fans out to all peers at once)

| Agents | Payload | Messages | mean | p95 | p99 | round wall ms |
|---|---|---|---|---|---|---|
| 10 | 64   | 450  | 0.999  | 2.566  | 3.521  | 12.4  |
| 10 | 512  | 450  | 0.827  | 2.334  | 3.888  | 9.6   |
| 10 | 4096 | 450  | 2.886  | 8.550  | 12.421 | 32.5  |
| 20 | 64   | 1900 | 1.575  | 4.618  | 6.762  | 35.5  |
| 20 | 512  | 1900 | 2.203  | 6.145  | 9.480  | 50.0  |
| 20 | 4096 | 1900 | 6.628  | 18.865 | 27.122 | 146.1 |
| 40 | 64   | 7800 | 4.859  | 12.877 | 18.630 | 215.0 |
| 40 | 512  | 7800 | 6.214  | 16.774 | 24.009 | 273.6 |
| 40 | 4096 | 7800 | 15.595 | 40.362 | 58.003 | 669.4 |

Reference point-to-point (connectivity test, single pair): session setup ~5-6 ms
cold, publish ~0.4 ms.

## Reading of the result

- Broker setup is validated. Real SLIM unicast full mesh delivers 100% at every
  config up to 40 agents / 1560 edges / 4 KB payload (~49,500 messages across the
  sweep); received == sent everywhere.
- Sequential latency is a sub-millisecond floor, near-flat in agent count and driven
  mostly by payload (0.05-0.10 ms at 64-512 B, ~0.35 ms at 4 KB).
- Concurrent fanout is where the cost shows: latency rises with both agent count and
  payload. Worst case (40 agents, 4 KB, all firing together) is mean 15.6 ms, p99
  58 ms — still bounded, no drops. This is the number that matters for "20+ agents all
  talking through SLIM at once".
- Round wall-clock grows roughly with total message volume; useful as a throughput proxy.

## Not done yet (next steps for the comparison sweep)

1. HTTP-direct transport on the same mesh driver (reuse the A2A HTTP path) — the first
   comparison leg.
2. A2A-over-SLIM transport — pending Sridharan's definition (A2A JSON-RPC envelope
   tunnelled over a SLIM channel vs. something more specific).
3. Agent-count sweep beyond 40 (80 / 160) to find where SLIM unicast knees over.
4. Run discipline: tear down and rebuild the node per config and automate ~10 repeats
   (Sai's wrapper). The harness already namespaces agents per run so an in-process
   sweep is safe; a node-per-config wrapper is the stricter version.
