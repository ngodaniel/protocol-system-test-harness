## Overview
This repository implements a system-level test harness for a simulated embedded device that exposes both control-plane and data-plane interfaces. The project is intentionally designed to resemble real-world validation environments used for FPGA, ASIC, and firmware-adjacent systems rather than a simplified unit-test demo.

The harness validates:
- Cross-protocol behavior (HTTP control →  UDP runtime effects)
- Stateful protocol interactions
- Fault handling under packet loss, delay, and corruption
- Client-side retry policy correctness
- Deterministic corruption detection via CRC

## System Under Test
The System Under Test (SUT) is a simulated device that models a stateful embedded component.

### Device Characteristics
- Maintains explicit internal state (`IDLE`, `CONFIGURED`, `STREAMING`)
- Accepts control commands via HTTP
- Process time-sensitive protocol commands via UDP
- Supports fault injection to emulate degraded hardware behavior.

### Exposed Interfaces
#### Control Panel (HTTP / FastAPI)
- `/health` -- liveness and state reporting
- `/control/reset` -- reset device state
- `/control/configure` -- transition to configured state
- `/control/faults` -- inject drop, delay, and corruption faults

##### Data Plane (UDP / Binary Protocol)
- `PING` -- connectivity check
- `STATUS` -- current device state
- `START`/`STOP` -- state transitions enforced by protocol rules
## Architecture
The project is split into three primary layers:
```perl
┌────────────────────────────┐
│        Test Layer          │
│  (pytest smoke/system)     │
└─────────────▲──────────────┘
              │
┌─────────────┴──────────────┐
│     QA Harness Layer       │
│  - HTTP client             │
│  - UDP client              │
│  - Framing / CRC           │
│  - Retry policy            │
└─────────────▲──────────────┘
              │
┌─────────────┴──────────────┐
│      Device Simulator      │
│  - FastAPI control plane   │
│  - asyncio UDP protocol    │
│  - state machine           │
│  - fault injection         │
└────────────────────────────┘
```
This separation mirrors production test stacks, where:
- Test logic never talks directly to device internals
-  Protocol behavior is validated externally 
- Faults are injected through supported interfaces only

## Quick Start
### Requirements
- Python 3.10+
- Windows or Linux (Windows-first supported)
- `pip`
### Setup
```bash
python -m venv .venv
source .venv/bin/activate	# windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]
```
No Docker or external services are required

## Running Tests
### Smoke Tests (fast, availability-focused)
```bash
pytest -m smoke
```
Smoke tests validate:
- Simulator startup
- HTTP availability
- Basic UDP connectivity

### System Tests (behavioral, fault-aware)
```bash
pytest -m system
```
System tests validate:
- Cross-protocol state transitions
- Retry behavior under packet loss
- CRC-based corruption detection
- Delay handling without blocking the event loop

### Full Test Suite
```bash
pytest
```

## Fault Injection
Fault inject is a **first-class feature** of the simulator and is intentionally persistent until cleared.
### Support Faults
| Fault Type | Effect |
|--|--|
| Drop | Packet is silently discarded |
| Delay | Response is delayed without blocking the event loop |
| Corruption | Response payload is altered, causing CRC failure |
#### Example
```python
sim_api.set_faults(
	drop_rate=0.7,
	delay_ms=0,
	corrupt_rate=0.0,
)
```
Faults persist across tests unless explicitly reset, modeling real-world misconfiguration scenarios.

## Reports & Artifacts
The harness produces machine-readable and human-readable artifact.
### Generated Outputs
- JUnit XML (`junit-*.xml`) for CI systems
- HTML test reports (optional)
- Simulator logs on failure

Artifacts are written to: `artifacts/`
This directory is ignored by git but uploaded automatically in CI.

## CI Pipeline
The CI pipeline is implemented using GitHub Actions and enforced quality gates.
### Pull Requests
- Lint (`ruff`)
- Type checks (`mypy`)
- Smoke test only (fast feedback)
### Main Branch
- Full system test suite
- Multi-OS (Windows + Linux)
- Multi-Python version matrix
- Artifact upload for debugging
### Nightly (optional)
- Full regression
- Artifact retention
- Flake and performance analysis ready

This mirrors how real hardware test pipelines separate PR validation from full regression
## Design Decisions
This project was intentionally designed to model real-world system-level testing challenges encountered in embedded, FPGA, and hardware-adjacent environments. The following decisions reflect tradeoffs commonly made in production test harnesses rather than simplified demo code.

The decisions documented below reflect real tradeoffs made in production test harnesses rather than simplified demo implementations. Emphasis is placed on determinism, diagnosability, and platform realism

### 1. Separation of Control Plane and Data Plane
#### Decision: 
The simulator exposes:

 - **HTTP (FastAPI)** for control and configuration
 - **UDP** for time-critical, protocol-level communication

#### Rationale:
In real systems, control and data paths are often separated:
- Control plane: configuration, reset, fault injection, health checks
- Data plane: low-latency, state-dependent communication
This separation allows:
- Independent testing of configuration vs. runtime behavior
- Realistic failure scenarios (e.g., data path misbehaves while control plane is healthy)
- Cross-protocol state validation (HTTP → UDP behavior)

### 2. Binary Framing Instead of Plaintext UDP
#### Decision:
All UDP traffic uses an explicit binary frame:

```pgsql
MAGIC | VERSION | TYPE | LENGTH | PAYLOAD | CRC32
```

#### Rationale:
Plaintext UDP masks many real defects. Binary framing enables:
- Deterministic corruption detection (CRC mismatch)
- Explicit protocol versioning
- Clear separation between transport errors and application errors

This mirrors real embedded protocols used over UART, SPI, Ethernet, or proprietary links.

### 3. CRC-Based Corruption Detection (Not Heuristics)
#### Decision:
Corruption is detected via **CRC32 validation**, not string inspection or sentinel bytes
#### Rationale:
Heuristic corruption detection (e.g., checking for invalid characters) produce false positives and hides edge cases. CRC:
- Detects single-bit and multi-bit corruption
- Enables deterministic test assertions
- Cleanly separates corruption from packet loss

Tests explicitly expect CRC failures when corruption is injected.

### 4. Fault Injection as First-Class Concept
#### Desision:
Faults are modeled explicitly and independently:
- Packet drop
- Packet delay
- Packet corruption
#### Rationale:
Real systems fail in different ways, and test logic must distinguish them:
- Drop → retryable
- Delay → timing-sensitive
- Corruption → non-retryable, must be detected

Faults persists until cleared to model misconfigured or degraded hardware

### 5. Retry Logic Is Client-Side and Policy-Driven
#### Decision:
Retry behavior lives in client, not the simulator, and is governed by a `RetryPolicy`.
#### Rationale:
In production systems:
- Devices do not retry on behalf of clients
- Retry strategies vary by use case

This allows tests to assert:
- Correct retry behavior under packet loss
- No retries on deterministic failures (e.g., CRC mismatch)

### 6. Async-Safe UDP Handling (No Blocking)
#### Decision:
The UDP protocol handler:
- Never blocks the event loop
- Uses immediate sends or schedules callbacks (`call_later`)
- Avoids `time.sleep` entirely
#### Rationale:
Blocking the event loop causes cross-protocol failures (UDP delays freezing HTTP).
The chosen approach ensures:
- HTTP and UDP remain responsive under fault injection
- Platform-safe behavior (Windows and Linux)

### 7. State Mutation After Response Decision
#### Decision:
Protocol handlers determines the response **before mutating system state**.
#### Rationale:
This avoids subtle race conditions where:
- State changes interfere with response emission
- Cross-protocol interactions (HTTP + UDP) create timing bugs

This pattern is common in firmware and protocol stacks where determinism is critical

### 8. Test Layering Strategy
#### Decision:
Tests are intentionally layered:
- Smoke tests → availability and basic connectivity
- System tests → cross-protocol behavior, state transitions, fault handling 
#### Rationale:
Smoke tests must remain stable as APIs evolve.
Behavioral and contract validation belongs in system tests

This separation mirrors production CI pipelines

### 9. Windows-First Development Assumption
#### Decision:
The harness explicitly supports Windows:
- Uvicorn launched as a subprocess
- No reliance on POSIX-only signals
- Async patterns validated on Windows event loop
#### Rationale:
Many hardware and FPGA test environments run on Windows.
Designing for Windows first exposes async and subprocess edge cases often missed on Linux

### 10. Why a Simulator Instead of Mocks
#### Decision
A real simulation process is used instead of mocking network calls.
#### Rationale:
Mocks cannot reproduce
- Timing issues
- Event loop starvation
- UDP packet loss behavior
- Cross-protocol race conditions

The simulator enables **system-level failure modes**, which is the primary goal of of this project.