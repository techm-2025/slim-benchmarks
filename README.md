# slim-benchmarks

This repository contains benchmark and validation assets for SLIM transport behavior, with runnable demos for multi-agent fanout, latency, SLIM-vs-HTTP comparison, and encryption overhead.

## Source Document Basis

The baseline validation document (`slim1.0(1).docx`) covered:
- security gate checks
- health endpoint performance (`/health`)
- scale levels at concurrency `5`, `20`, `50`

This repo now extends that baseline with additional, reproducible scenarios focused on agent-to-agent messaging patterns.

## Expanded Scenario Matrix

### S1: Multi-Agent Fanout (`A -> B,C,D,E`)
- **Goal:** verify one orchestrator agent can call the other four agents in parallel.
- **Transport path:** HTTP JSON-RPC (`a2a-sdk` server).
- **Metric:** fanout round latency in milliseconds.

### S2: SLIM-style Fanout Baseline
- **Goal:** compare the fanout pattern with a low-overhead in-memory bus approximation.
- **Transport path:** in-process async bus (demo proxy for SLIM semantics).
- **Metric:** fanout round latency in milliseconds.

### S3: SLIM vs HTTP Latency
- **Goal:** quantify overhead differences across the same topology and payload.
- **Method:** run S1 and S2 with identical rounds and payload size.
- **Metric:** mean, median, p50, p95, min, max.

### S4: Encryption Overhead
- **Goal:** measure encrypted payload cost in the SLIM-style path.
- **Method:** compare plain payload vs Fernet-encrypted payload.
- **Metric:** `delta_mean_ms` (encrypted mean - plain mean).

## Demo Script

`A2A-MAS-no-SLIM/demo_benchmark.py`

What it does:
- boots 5 local agents (`A,B,C,D,E`) on consecutive ports
- executes HTTP fanout (`A` calls `B,C,D,E`)
- executes SLIM-style fanout with an in-memory bus
- executes encryption-overhead scenario
- prints structured JSON results

Run:

```bash
cd A2A-MAS-no-SLIM
uv run --python /Users/xiaodonz/Documents/GitHub/slim-benchmarks/.venv-uv/bin/python python demo_benchmark.py --rounds 50 --base-port 8100 --payload-size 64 --output demo_results.json
```

## Test Script

`A2A-MAS-no-SLIM/test_demo_benchmark.py`

What it checks:
- all three benchmark scenarios are returned
- each scenario returns valid sample counts and latency bounds

Run:

```bash
cd A2A-MAS-no-SLIM
uv run --python /Users/xiaodonz/Documents/GitHub/slim-benchmarks/.venv-uv/bin/python python -m unittest -v test_demo_benchmark.py
```

## Dependencies

Install:

```bash
cd A2A-MAS-no-SLIM
uv venv ../.venv-uv
uv pip install --python ../.venv-uv/bin/python -r requirements.txt
```

Added for encryption scenario:
- `cryptography`

## Notes on Interpretation

- The in-memory bus is a demo approximation of SLIM behavior used for relative latency comparison in local tests.
- Absolute numbers vary by host performance and background load.
- For production-level decisions, repeat runs across multiple payload sizes and longer durations.