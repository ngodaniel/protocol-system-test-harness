import os
import subprocess
import time
import sys
import socket
import json
from pathlib import Path

import pytest
import httpx

from qaharness.config.settings import get_settings
from qaharness.api.client import SimApiClient
from qaharness.transport.udp import UdpClient, UdpEndpoint
from qaharness.transport.tcp import TcpClient, TcpEndpoint

REPO_ROOT = Path(__file__).resolve().parents[1]

def _wait_for_udp_ready(host: str, port: int, timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            sock.sendto(b"__", (host, port))
            return
        except Exception:
            time.sleep(0.2)
        finally:
            sock.close()
    raise RuntimeError(f"UDP did not become ready on {host}:{port}")

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    
def _wait_for_http_ready(url: str, proc: subprocess.Popen, timeout_s: float = 15.0) -> None:
    """
    Wait for the simulator to respond at url. If the process exits, surface logs.
    """
    deadline = time.time() + timeout_s
    buffered = []

    while time.time() < deadline:
        # If process died, show output immediately
        if proc.poll() is not None:
            out = ""
            if proc.stdout:
                out = proc.stdout.read() or ""
            raise RuntimeError(
                f"Simulator exited early (code={proc.returncode}).\n"
                f"--- simulator output ---\n{out}"
            )

        # Check HTTP
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass

        # Capture a little stdout for debugging, without blocking forever
        if proc.stdout:
            try:
                line = proc.stdout.readline()
                if line:
                    buffered.append(line)
                    if len(buffered) > 80:
                        buffered = buffered[-80:]
            except Exception:
                pass

        time.sleep(0.2)

    raise RuntimeError(
        f"Simulator did not become ready at {url} within {timeout_s}s.\n"
        f"--- last simulator output ---\n{''.join(buffered)}"
    )

@pytest.fixture(scope="session", autouse=True)
def simulator_process():
    """
    Starts the simulator automatically for the test session (Windows-friendly).
    Uses `py -m uvicorn ...` from repo root so `services.*` imports resolve.
    """

    # Keep a single source of truth for where tests expect the API
    # If you want to change ports later, change it here and in settings defaults.
    sim_host = "127.0.0.1"
    sim_port = int(os.getenv("SIM_HTTP_PORT", _free_port()))
    sim_http = os.getenv("SIM_HTTP", f"http://{sim_host}:{sim_port}")

    #env = os.environ.copy()
    #env["SIM_HTTP"] = sim_http
    #env["SIM_HTTP_HOST"] = sim_host
    #env["SIM_HTTP_PORT"] = str(sim_port)
    #env["SIM_UDP_HOST"] = os.getenv("SIM_UDP_HOST", "127.0.0.1")
    #env["SIM_UDP_PORT"] = os.getenv("SIM_UDP_PORT", str(_free_port()))

    os.environ["SIM_HTTP"] = sim_http
    os.environ["SIM_HTTP_HOST"] = sim_host
    os.environ["SIM_HTTP_PORT"] = str(sim_port)
    os.environ["SIM_UDP_HOST"] = os.getenv("SIM_UDP_HOST", "127.0.0.1")
    os.environ["SIM_UDP_PORT"] = os.getenv("SIM_UDP_PORT", str(_free_port()))
    os.environ["SIM_TCP_HOST" ] = os.getenv("SIM_TCP_HOST", "127.0.0.1")
    os.environ["SIM_TCP_PORT"] = os.getenv("SIM_TCP_PORT", str(_free_port()))


    env = os.environ.copy()
    # Start uvicorn as a module, from repo root
    cmd = [
        sys.executable, "-m", "uvicorn",
        "services.device_sim.app.main:app",
        "--host", sim_host,
        "--port", str(sim_port),
        "--log-level", "info",
    ]

    p = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    try:
        _wait_for_http_ready(
            f"{sim_http}/health", 
            p, 
            timeout_s=15.0
        )
        _wait_for_udp_ready(
            env["SIM_UDP_HOST"],
            int(env["SIM_UDP_PORT"]),
            timeout_s=5.0,
        )
        _wait_for_tcp_ready(
            env["SIM_TCP_HOST"],
            int(env["SIM_TCP_PORT"]),
            timeout_s=5.0,
        )
        yield p
    except Exception:
        if p.stdout:
            out = p.stdout.read()
            if out:
                print("\n--- simulator output (on failure) ---\n", out)
        raise
    finally:
        # Graceful terminate, then force kill if needed
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()

@pytest.fixture
def settings():
    return get_settings()

@pytest.fixture
def sim_api(settings):
    client = SimApiClient(settings.sim_http)
    try:
        yield client
    finally:
        client.close()

@pytest.fixture
def sim_udp(settings):
    return UdpClient(UdpEndpoint(settings.sim_udp_host, settings.sim_udp_port))

@pytest.fixture
def sim_udp_perf(settings):
    return UdpClient(UdpEndpoint(settings.sim_udp_host, settings.sim_udp_port), timeout_s=0.2)

@pytest.fixture(scope="function", autouse=True)
def reset_simulator(sim_api):
    """
    ensure each test starts from a clean state AND clean fault config
    """
    # clear faults first 
    sim_api.set_faults(delay_ms=0, drop_rate=0.0, corrupt_rate=0.0)

    # reset state
    sim_api.reset()
    yield

@ pytest.fixture
def sim_tcp(settings):
    return TcpClient(TcpEndpoint(settings.sim_tcp_host, settings.sim_tcp_port))

def _free_udp_port(host: str = "127.0.0.1") -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host, 0)) 
    port = s.getsockname()[1]
    s.close()
    return port

def _wait_for_tcp_ready(host: str, port: int, timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"TCP did not become ready on {host}:{port}")


def _artifact_dir() -> Path:
    p = Path("artifacts") / "metrics"
    p.mkdir(parents=True, exist_ok=True)
    return p

@pytest.fixture
def metrics_recorder(request):
    """
    Usage:
        metric_recorder({
            "name": "delay_envelope_udp_ping",
            "p50_ms", 123.4,
            ...
        })
    writes one JSON file per test
    """
    start = time.time()
    records = []
    def record(payload: dict):
        records.append(payload)

    yield record

    # write on teardown (even if test failed, if fixture teardown runs)
    test_id = request.node.nodeid.replace("/", "_").replace("::", "__")
    out = {
        "test_id": request.node.nodeid,
        "timestamp_epoch": start,
        "duration_s": time.time() - start,
        "records": records,
    }

    out_path = _artifact_dir() / f"{test_id}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

def pytest_sessionstart(session):
    d = Path("artifacts")
    d.mkdir(exist_ok=True)
    session.config._qa_metrics_summary = {
        "started_at": time.time(),
        "tests": [],
    }

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    t0 = time.time()
    outcome = yield
    dt = time.time() - t0
    item.config._qa_metrics_summary["tests"].append({
        "nodeid": item.nodeid,
        "duration_s": dt,
        "status": "passed" if outcome.excinfo is None else "failed",
    })

def pytest_sessionfinish(session, exitstatus):
    summary = session.config._qa_metrics_summary
    summary["finished_at"] = time.time()
    summary["existatus"] = exitstatus
    out = Path("artifacts") / "metrics_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding='utf-8')