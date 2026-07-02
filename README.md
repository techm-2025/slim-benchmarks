# slim-benchmarks — A2A over SLIM

Benchmarks the question: **does routing A2A agent traffic through SLIM add latency, or is it efficient?**

Uses the public [`slima2a`](https://pypi.org/project/slima2a/) package (v0.6.0) so results are fully reproducible without internal tooling.

---

## How it works

N echo agents run as separate OS processes (true parallelism). Every agent acts as both server and client — it hosts an A2A echo server over SLIM and sends `SendMessage` requests to every other agent. Traffic is routed through a local SLIM node.

One **measured unit** = one full A2A round trip: `SendMessage` sent → task result artifact received, timed with `time.perf_counter()`. Setup and connection time are excluded from all measurements.

Two fan-out modes are tested:

| Mode | Description |
|---|---|
| `sequential` | Each agent awaits one peer at a time |
| `concurrent` | Each agent fans out to all peers simultaneously via `asyncio.gather` |

A run is only valid at **100% delivery**. Any missing responses are counted and the run is flagged FAIL.

---

## Setup

### 1. Prerequisites

- Docker (to run the SLIM node)
- Python 3.11+

### 2. Start the SLIM node

The `slima2a` package requires `slim-bindings>=1.4`, which needs a **1.4.x SLIM node**. The `server-config.yaml` in this repo is ready to use.

```bash
docker run --rm -d --name slim-node \
  -p 46357:46357 \
  -v "$PWD/server-config.yaml:/config.yaml" \
  --entrypoint /slim \
  ghcr.io/agntcy/slim:1.4.0 --config /config.yaml
```

Verify it is running:

```bash
docker ps --filter name=slim-node
```

To stop it later:

```bash
docker stop slim-node
```

### 3. Create the Python environment

```bash
python3.11 -m venv .venv-a2a
.venv-a2a/bin/pip install -e .
```

> If you also have the legacy `.venv/` from earlier SLIM 1.3 work, keep it separate — the two environments have different `slim-bindings` versions and are not interchangeable.

---

## Running the benchmark

All commands assume the SLIM node is running and `.venv-a2a` is set up.

### Quick smoke test — 5 agents, 3 rounds

```bash
.venv-a2a/bin/python a2a_slim_mesh_benchmark.py \
  --agents 5 \
  --rounds 3 \
  --payload-size 64
```

This runs the sequential fan-out mode and prints per-run latency stats.

### Concurrent fan-out

Add `--concurrent` to fan out to all peers in parallel per round:

```bash
.venv-a2a/bin/python a2a_slim_mesh_benchmark.py \
  --agents 5 \
  --rounds 3 \
  --payload-size 64 \
  --concurrent
```

### Scale sweep — multiple agent counts and payload sizes

Runs both sequential and concurrent modes across every combination of `--agents-list` × `--payloads` and writes results to a JSON file:

```bash
.venv-a2a/bin/python a2a_slim_mesh_benchmark.py \
  --sweep \
  --agents-list 5,10,20 \
  --payloads 64,512 \
  --rounds 3 \
  --output docs/evidence/a2a_slim_mesh_sweep.json
```

### All CLI options

| Flag | Default | Description |
|---|---|---|
| `--agents N` | 5 | Number of agents (= number of OS processes) |
| `--rounds N` | 1 | Rounds of messages per agent pair |
| `--payload-size N` | 64 | Payload size in bytes |
| `--concurrent` | off | Fan out to all peers in parallel per round |
| `--sweep` | off | Run all combinations of agents × payloads |
| `--agents-list A,B,...` | 5,10,20 | Agent counts to sweep (used with `--sweep`) |
| `--payloads A,B,...` | 64 | Payload sizes to sweep (used with `--sweep`) |
| `--output PATH` | (stdout) | Write JSON report to this file |

---

## Reading the output

Each result row looks like:

```
[RESULT] n=  5  pay=  64B  sequential  trips=   20  done=   20  mean=  9.69ms  p95= 21.72ms  p99= 23.50ms  wall=    8898ms  delivery=100.0%
```

| Column | Meaning |
|---|---|
| `n` | Number of agents |
| `pay` | Payload size |
| `mode` | `sequential` or `concurrent` |
| `trips` | Total round trips measured |
| `done` | Round trips successfully delivered — must equal `trips` |
| `mean` | Mean round-trip latency |
| `p95` | 95th-percentile latency |
| `p99` | 99th-percentile latency |
| `wall` | Total wall-clock time for this run |
| `delivery` | Must be 100% for the run to be valid |

The JSON output (when `--output` is set) contains the full per-run stats plus metadata including package versions, SLIM node image, and delivery count.

---

## Results and findings

Full sweep results are in [`docs/evidence/a2a_slim_mesh_sweep.json`](docs/evidence/a2a_slim_mesh_sweep.json).  
Full analysis is in [`docs/FINDINGS.md`](docs/FINDINGS.md).

### Sequential mode — SLIM vs HTTP baseline

The `feat/full-mesh-scale-bench` branch has matching A2A/HTTP measurements (no SLIM, direct loopback):

| Transport | 5-agent mean | 10-agent mean | 20-agent mean | SLIM overhead |
|---|---|---|---|---|
| A2A over HTTP (no SLIM) | 3.1 ms | 4.1 ms | 7.4 ms | baseline |
| **A2A over SLIM (this branch)** | **5.6 ms** | **7.5 ms** | **14.6 ms** | **~1.85–1.9×** |

SLIM adds a consistent ~1.85× overhead — approximately 2.5–7 ms per hop — which is negligible relative to any real agent computation.

### Concurrent burst fan-out

| Agents | In-flight msgs | Mean | p95 | p99 | Max |
|---|---|---|---|---|---|
| 5  | 20  | 11.9 ms | 19 ms | 20 ms | 20 ms |
| 10 | 90  | 35.4 ms | 53 ms | 53 ms | 59 ms |
| 20 | 380 | 118 ms | 212 ms | 234 ms | 311 ms |

Concurrent burst degrades super-linearly at scale — a single-node bottleneck effect. At 20 agents, 380 simultaneous messages push mean latency to 118 ms. For interactive use, throttled fan-out or SLIM clustering would be needed at this scale.

### Delivery

**100% delivery across all 5,880 messages in all 12 scenarios.** SLIM does not sacrifice reliability under load.

---

## Versions

| Component | Version |
|---|---|
| `slima2a` | 0.6.0 |
| `slim-bindings` | 1.4.1 |
| `a2a-sdk` | 1.0.0-alpha.0 |
| SLIM node image | `ghcr.io/agntcy/slim:1.4.0` |
| Python | ≥ 3.11 |
