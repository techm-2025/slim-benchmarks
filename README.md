# slim-benchmarks

Python benchmarks and connectivity tests for [SLIM](https://github.com/agntcy/slim)
(Secure Low-Latency Interactive Messaging) using
[slim-bindings](https://pypi.org/project/slim-bindings/) v1.3.0.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.10 |
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
pip install -e ".[dev]"            # + pytest
```

### 3 — Run the connectivity test

```bash
# direct
python tests/test_connectivity.py

# via pytest
pytest tests/
```

---

## Project structure

```
slim-benchmarks/
├── slim_bench/               # shared package
│   ├── config.py             # constants, SLIM runtime init, session defaults
│   ├── display.py            # ANSI colour helpers, log()
│   ├── subscriber.py         # run_subscriber()
│   └── publisher.py          # run_publisher()
├── tests/
│   └── test_connectivity.py  # subscribe → publish → assert receipt
├── server-config.yaml        # SLIM node config (insecure, port 46357)
├── client-config.yaml        # Python-side runtime bootstrap config
└── pyproject.toml
```

---

## Configuration

| File | Purpose |
|---|---|
| `server-config.yaml` | Passed to the Docker container; configures the SLIM node listener |
| `client-config.yaml` | Reference only — the Python code calls `initialize_with_configs` directly |
| `slim_bench/config.py` | Edit `SLIM_ENDPOINT`, `SECRET`, `TIMEOUT`, `PAYLOAD` to change test parameters |

---

## Stop the SLIM node

```bash
docker stop slim-node
```
