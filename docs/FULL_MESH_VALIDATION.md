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
- Full mesh: every agent opens a `POINT_TO_POINT` session to every other agent and
  publishes one message per round. N x (N-1) directed edges.
- Metric: per-message `publish_and_wait` latency (delivery confirmed by the broker).

Delivery is verified, not assumed: the runner reports `messages_received_by_peers`
(summed `get_message` count across all agents) and it matches the send count.

## How to run

```bash
# 1. SLIM node
docker run --rm -d --name slim-node -p 46357:46357 \
  -v "$(pwd)/server-config.yaml:/config.yaml" \
  --entrypoint /slim ghcr.io/agntcy/slim:1.3.0 --config /config.yaml

# 2. venv (slim-bindings resolves on Python 3.12)
uv venv .venv-mesh --python python3
uv pip install --python .venv-mesh/bin/python slim-bindings==1.3.0

# 3. run
PYTHONPATH=. .venv-mesh/bin/python mesh_benchmark.py \
  --agents 20 --rounds 1 --payload-size 64 --output docs/evidence/full_mesh_n20.json
```

## Results (local, 2026-06-22, SLIM node ghcr.io/agntcy/slim:1.3.0)

| Agents | Directed edges | Sent | Received | mean ms | p50 ms | p95 ms | max ms |
|---|---|---|---|---|---|---|---|
| 4  | 12   | 12   | 12   | 0.161 | 0.107 | 0.305 | 0.506 |
| 20 | 380  | 380  | 380  | 0.092 | 0.080 | 0.162 | 1.109 |
| 40 | 1560 | 1560 | 1560 | 0.102 | 0.098 | 0.161 | 1.052 |

Raw JSON in `docs/evidence/full_mesh_n20.json` and `docs/evidence/full_mesh_n40.json`.

Reference point-to-point (connectivity test, single pair): session setup ~5-6 ms
cold, publish ~0.4 ms.

## Reading of the result

- Broker setup is validated. Real SLIM unicast full mesh delivers every message at
  N=20 (380 edges) and N=40 (1560 edges); received == sent in all runs.
- Per-message publish latency is flat from N=20 to N=40 (mean ~0.1 ms, p95 ~0.16 ms),
  so 20 agents is well within broker headroom and the harness scales for the sweep.
- These are sequential single-in-flight publishes — clean per-message latency, not a
  concurrency/congestion measurement. Concurrent fanout is a later sweep dimension.

## Not done yet (next steps for the comparison sweep)

1. HTTP-direct transport on the same mesh driver (reuse the A2A HTTP path).
2. A2A-over-SLIM transport — pending Sridharan's definition (A2A JSON-RPC envelope
   tunnelled over a SLIM channel vs. something more specific).
3. Agent-count sweep beyond 40 and multiple payload sizes (64 / 512 / 4096).
4. Concurrent fanout per round (all agents send simultaneously) to measure congestion.
5. Run discipline: start from a clean state, tear down and rebuild the node per run,
   automate ~10 runs (Sai's wrapper).
