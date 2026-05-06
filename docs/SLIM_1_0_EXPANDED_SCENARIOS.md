# SLIM 1.0 Expanded Validation Scenarios

This document extends the original SLIM 1.0 validation report with extra scenarios for agent fanout patterns, transport comparison, and encryption overhead.

## Added Scenarios

### E1: Five-Agent Topology (`A,B,C,D,E`)
- Agents used: `A` orchestrator, `B/C/D/E` workers.
- Purpose: deterministic topology for repeated benchmark runs.

### E2: Fanout Pattern (`A -> B,C,D,E`)
- Action: `A` calls all four peers in parallel per round.
- Outputs: total round latency and per-round distribution stats.

### E3: Latency Comparison (SLIM-style vs HTTP)
- HTTP path: loopback JSON-RPC style requests over local HTTP.
- SLIM-style path: in-memory async bus path with minimal framing overhead.
- Metric set: `mean`, `median`, `p50`, `p95`, `min`, `max`.

### E4: Encryption Overhead
- Baseline: plain payload over SLIM-style path.
- Encrypted: Fernet-encrypted payload over same path.
- Key metric: `delta_mean_ms = encrypted_mean_ms - baseline_mean_ms`.

## Demo + Test Artifacts

- Demo runner: `A2A-MAS-no-SLIM/demo_benchmark.py`
- Test script: `A2A-MAS-no-SLIM/test_demo_benchmark.py`
- Example output: `A2A-MAS-no-SLIM/demo_results.json`

## How To Run

```bash
cd A2A-MAS-no-SLIM
uv venv ../.venv-uv
uv pip install --python ../.venv-uv/bin/python -r requirements.txt
uv run --python /Users/xiaodonz/Documents/GitHub/slim-benchmarks/.venv-uv/bin/python python -m unittest -v test_demo_benchmark.py
uv run --python /Users/xiaodonz/Documents/GitHub/slim-benchmarks/.venv-uv/bin/python python demo_benchmark.py --rounds 10 --base-port 8600 --payload-size 64 --output demo_results_uv.json
```

## UV Execution Evidence (Proof)

Run timestamp (UTC): `2026-05-06T16:21:21Z`

Environment:
- `uv 0.8.9`
- Python interpreter: `/Users/xiaodonz/Documents/GitHub/slim-benchmarks/.venv-uv/bin/python`

Command log and output excerpts:

```bash
uv run --python /Users/xiaodonz/Documents/GitHub/slim-benchmarks/.venv-uv/bin/python --directory A2A-MAS-no-SLIM python -m unittest -v test_demo_benchmark.py
```

```text
test_run_demo_returns_all_scenarios ... ok
test_scenarios_have_samples ... ok
Ran 2 tests in 2.752s
OK
```

```bash
uv run --python /Users/xiaodonz/Documents/GitHub/slim-benchmarks/.venv-uv/bin/python --directory A2A-MAS-no-SLIM python demo_benchmark.py --rounds 10 --base-port 8600 --payload-size 64 --output demo_results_uv.json
```

```text
fanout_http_A_to_BCDE: mean 2.41 ms, p95 2.321 ms
fanout_slim_A_to_BCDE: mean 0.081 ms, p95 0.086 ms
encryption_overhead_slim: baseline_mean 0.014 ms, encrypted_mean 0.015 ms, delta_mean 0.0 ms
```

Artifacts generated:
- `A2A-MAS-no-SLIM/demo_results_uv.json`

## Demo Run Snapshot (Current Workspace)

Configuration:
- rounds: `10`
- payload_size: `64` bytes
- topology: `A -> B,C,D,E`

Observed summary:
- `fanout_http_A_to_BCDE`: mean `3.535 ms`, p95 `3.567 ms`
- `fanout_slim_A_to_BCDE`: mean `0.076 ms`, p95 `0.074 ms`
- `encryption_overhead_slim`: baseline mean `0.023 ms`, encrypted mean `0.022 ms`, delta `-0.001 ms`

UV run summary (latest):
- `fanout_http_A_to_BCDE`: mean `2.41 ms`, p95 `2.321 ms`
- `fanout_slim_A_to_BCDE`: mean `0.081 ms`, p95 `0.086 ms`
- `encryption_overhead_slim`: baseline mean `0.014 ms`, encrypted mean `0.015 ms`, delta `0.0 ms`

Notes:
- Numbers are from local loopback execution and mainly indicate relative behavior, not production SLA values.
- For report-grade results, run more rounds (for example `1000`) and include multiple payload sizes (`64`, `512`, `4096`).
