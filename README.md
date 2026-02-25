
## Overview

This repository implements a **system-level test harness** for a simulated embedded device with separated control-plane and date-plane interfaces.

It's designed to resemble real-world validation environments used for.
- FPGA / ASIC bring-up
- firmware-adjacent integration testing
- protocol verification

The harness validates:
- **Cross-protocol behavior** (HTTP control → UDP/TCP runtime effects)
- **Stateful protocol interactions**
- **Fault handling** under packet loss, delay, and corruption
- **Client-side retry policy correctness**
- **Deterministic corruption detection** via CRC-framed binary messages


## System Under Test
The System Under Test (SUT) is a simulated device that models a stateful embedded component.

### Device Characteristics
- Maintains explicit internal state (`IDLE`, `CONFIGURED`, `STREAMING`)
- Accepts control commands via HTTP (FastAPI)
- Processes protocol commands via:
	- **UDP** (datagram)
	- **TCP** (stream, framed)
- Supports fault injection to emulate degraded hardware/network behavior.


## Exposed Interfaces
### Control Panel (HTTP / FastAPI)

The simulator exposes a control API for health, state transition, and fault injection.

#### Key endpoints
- `GET /health` -- liveness + current state
- `GET /status` -- state + reset count + current fault config
- `POST /control/reset` -- reset device state
- `POST /control/configure` -- transition to `CONFIGURED`
- `POST /control/stream/start` -- transition to `STREAMING`
- `POST /control/stream/stop` -- stop streaming
- `POST /control/faults` -- set drop/delay/corruption faults
- `GET /control/faults` -- read current fault settings

#### UI
- `GET /ui` -- simple web UI for manual interaction
- Static assets served under `/ui/static`

---

### Data Plane (Binary Protocol over UDP/TCP)

Both UDP and TCP use the same binary framing contract:
```text
MAGIC | VERSION | TYPE | LENGTH | PAYLOAD | CRC32
```
#### Supported request types:
- `PING` -- connectivity check
- `STATUS` -- current device state
- `START`/`STOP` -- state transitions enforced by protocol rules

#### Responses include:
- OK / state payloads
- protocol errors (e.g., bad state)
- CRC-detectable corruption failures when fault injection is enabled
## Architecture
The project is split into three primary layers:
```perl
┌────────────────────────────┐
│        Test Layer          │
│   (pytest smoke/system)    │
└─────────────▲──────────────┘
              │
┌─────────────┴──────────────┐
│      QA Harness Layer      │
│  - HTTP client             │
│  - UDP client              │
│  - TCP client              │
│  - Framing / CRC           │
│  - Retry policy            │
└─────────────▲──────────────┘
              │
┌─────────────┴──────────────┐
│     Device Simulator       │
│  - FastAPI control plane   │
│  - asyncio UDP protocol    │
│  - asyncio TCP server      │
│  - state machine           │
│  - fault injection         │
└────────────────────────────┘
```
This separation mirrors production test stacks, where:
- Test logic does **not** talk directly to device internals
-  Protocol behavior is validated externally 
- Faults are injected only through supported interfaces 

## Quick Start
### Requirements
- Python 3.10+
- Windows or Linux (Windows-first supported)
- `pip`
### Setup
```bash
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
.\.venve\Scripts\Activate.ps1

pip install -e ".[test]"
```
No Docker or external services are required

## Running the Simulator UI
### Start the Simulator:
```bash
uvicorn services.device_sim.app.main:app --reload
```
### Open the UI in your browser:
- `http://127.0.0.1:8000/ui
### Health check:
- `http://127/0.0.1:8000/health

## Running Tests
### Smoke Tests (fast / availability-focused)
```bash
pytest -m smoke
```
Smoke tests validate:
- simulator startup
- HTTP availability
- basic UDP connectivity

### System Tests (behavioral, fault-aware)
```bash
pytest -m system
```
System tests validate:
- cross-protocol state transitions 
- retry behavior under packet loss
- CRC-based corrupt detection
- delay handling without blocking the event loop
- framed protocol behavior over UDP/TCP

### Full Test Suite
```bash
pytest
```

## Fault Injection
Fault inject is a **first-class feature** of the simulator and is intentionally persistent until cleared.
### Support Faults
| Fault Type | Effect |
|--|--|
| Drop | Packet/response is silently discarded |
| Delay | Response is delayed without blocking the event loop |
| Corruption | Response bytes are modified after encoding (CRC mismatch) |
#### Example
```python
sim_api.set_faults(
	drop_rate=0.7,
	delay_ms=0,
	corrupt_rate=0.0,
)
```
#### Read current faults
```bash
curl http://127.0.0.1:8000/control/faults
```

## Reports & Artifacts
The harness is designed to generate CI-friendly artifacts under `artifacts/`:
- JUnit XML reports
- HTML reports (optional)
- simulator logs (on failure)
- performance metrics JSON (if enabled)
- SQLite test telemetry DB (`artifacts/results.db`)

This directory is safe to upload from CI jobs for debugging and trend analysis.

## CI Pipeline
The CI pipeline (GitHub Actions) is structured to mirror production QA workflows.

### Recommended stages
#### Pull Requests
- lint (`ruff`)
- type checks (`mypy`)
- smoke tests only (fast feedback)
- artifact upload on failure
#### Main Branch
- full system suite
- multi-OS / multi-Python matrix
- coverage + threshold gate
- artifact upload (`artifacts/`)
#### Perf / Envelope job
- targeted performance envelope tests
- env-tunable thresholds (p50/p95, success rate)
- metrics artifact upload
#### Nightly
- longer-run regression
- larger perf sample sizes
- flake/perf trend collection

## SQL Telemetry
This project is a strong fit for SQL-backed test observability.

A recommended pattern is to persist test telemetry to SQLite (later portable to Postgres):

### Suggested tables
- `test_runs`
- `test_results`
- `perf_metrics`
- `retry_events`
#### This supports:
- flaky test analysis
- latency trend tracking (p50/p95)
- retry pattern analysis under fault injection
- historical CI run comparisons
#### Artifacts can include:
- `artifacts/results.db`
- `artifacts/metrics/*.json`

## Design Decisions
This project intentionally models real system-level testing constraints instead of a simplified unit-test demo.

### 1. Control plane vs data plane separation
- HTTP handles configuration, reset, fault injection, health
- UDP/TCP handles runtime protocol behavior

This enables realistic cross-protocol validation (e.g., HTTP state change reflected in protocol responses)

### 2. Binary framing instead of plaintext
All protocol traffic is framed and CRC-protected to support:
- deterministic corruption detection
- protocol versioning
- strict parsing behavior

### 3. Fault injection as a first-class capability
Drop, delay, and corruption are independently configurable and persistent until reset.
This models real degraded-system behavior and supports meaningful retry/corruption tests.

### 4. Retry logic is client-side and policy driven
Retry behavior in the harness client, not the simulator, which reflects production design and allows targeted assertions.

### 5. Async-safe protocol handling
The simulator avoids blocking behavior in protocol handlers, which protects HTTP responsiveness even under delay faults.

### 6. Simulator over mocks
A real process and real sockets are used because mocks do not reproduce:
- timing issues
- event-loop starvation
- packet loss / corruption behavior
- cross-protocol race conditions

## Current Status / Next Enhancements
Recent additions already present in the simulator include:
- TCP protocol support (framed, retry-capable client)
- `/ui` web interface
- `GET /control/faults