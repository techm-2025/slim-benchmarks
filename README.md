# slim-benchmarks

Python benchmarks, connectivity tests, and security demonstrations for
[SLIM](https://github.com/agntcy/slim) (Secure Low-Latency Interactive Messaging)
using [slim-bindings](https://pypi.org/project/slim-bindings/) v1.3.0.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.11 |
| Docker | any recent version |

---

## Quick start

### 1 — Start the SLIM node

```bash
docker run --rm -d --name slim-node \
  -p 46357:46357 \
  -v $(pwd)/server-config.yaml:/config.yaml \
  --entrypoint /slim \
  ghcr.io/agntcy/slim:1.3.0 --config /config.yaml
```

Confirm it is running:

```bash
docker logs slim-node
# expect: dataplane server started endpoint=0.0.0.0:46357
```

### 2 — Create a virtual environment and install dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e .                   # runtime deps (slim-bindings==1.3.0)
pip install -e ".[dev]"            # + pytest, nats-py, matplotlib, etc.
```

### 3 — Run the connectivity test

```bash
# direct
python tests/test_connectivity.py

# via pytest
pytest tests/test_connectivity.py
```

---

## Security comparison demo

Proves end-to-end encryption in SLIM vs unencrypted NATS using a transparent
TCP proxy that logs every byte passing between client and broker/relay.

**Known plaintext under test:** `SLIM_SECURITY_DEMO_PLAINTEXT_2026`

### Step 1 — SLIM relay capture

```bash
# SLIM node must already be running (see Quick start step 1)
python tests/test_slim_capture.py
```

A Python proxy on port `46360` forwards all traffic to the SLIM relay on `46357`
and logs every byte.
**Expected:** the plaintext string is NOT present anywhere in the 12 captured frames — the relay
sees only opaque ciphertext.

Output: `captures/slim_hexdump.txt`

### Step 2 — NATS broker capture

```bash
# Pulls and starts nats:latest automatically; Docker must be running
python tests/test_nats_capture.py
```

Same proxy technique against a NATS broker on port `4222` (no TLS).
**Expected:** the plaintext string IS visible verbatim inside a single 55-byte
`PUB bench.demo 33\r\n…` frame — the broker sees the full message.

Output: `captures/nats_hexdump.txt`

### Step 3 — Side-by-side report

```bash
# Reads the two hex dumps produced above
python tests/generate_report.py
```

Outputs:
- `captures/comparison_report.txt` — text side-by-side of the payload frames
- `captures/comparison.png` — matplotlib figure with highlighted hex dumps

> `captures/` is git-ignored; all files there are regenerated on each run.

---

## Project structure

```
slim-benchmarks/
├── slim_bench/                  # shared package
│   ├── config.py                # constants, SLIM runtime init, session defaults
│   ├── display.py               # ANSI colour helpers, log()
│   ├── subscriber.py            # run_subscriber()
│   └── publisher.py             # run_publisher()
├── tests/
│   ├── test_connectivity.py     # subscribe → publish → assert receipt
│   ├── test_slim_capture.py     # proxy capture: SLIM relay sees ciphertext
│   ├── test_nats_capture.py     # proxy capture: NATS broker sees plaintext
│   └── generate_report.py       # side-by-side text + PNG comparison
├── captures/                    # generated output — git-ignored
│   ├── slim_hexdump.txt
│   ├── nats_hexdump.txt
│   ├── comparison_report.txt
│   └── comparison.png
├── server-config.yaml           # SLIM node config (insecure, port 46357)
├── client-config.yaml           # reference only
└── pyproject.toml
```

---

## Configuration

| File | Purpose |
|---|---|
| `server-config.yaml` | Passed to the Docker container; configures the SLIM node listener |
| `client-config.yaml` | Reference only — Python code calls `initialize_with_configs` directly |
| `slim_bench/config.py` | Edit `SLIM_ENDPOINT`, `SECRET`, `TIMEOUT`, `PAYLOAD` to change test parameters |

---

## Stop services

```bash
docker stop slim-node       # SLIM relay
docker stop nats-bench      # NATS broker (only running during test_nats_capture.py)
```
