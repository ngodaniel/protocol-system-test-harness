import os
import subprocess
import time
import sys
from pathlib import Path

import pytest
import httpx

from qaharness.config.settings import get_settings
from qaharness.api.client import SimApiClient
from qaharness.transport.udp import UdpClient, UdpEndpoint

REPO_ROOT = Path(__file__).resolve().parents[1]

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
    settings = get_settings()

    # Keep a single source of truth for where tests expect the API
    # If you want to change ports later, change it here and in settings defaults.
    sim_host = "127.0.0.1"
    sim_port = int(os.getenv("SIM_HTTP_PORT", "8000"))
    sim_http = os.getenv("SIM_HTTP", f"http://{sim_host}:{sim_port}")

    env = os.environ.copy()
    env["SIM_HTTP"] = sim_http
    env["SIM_HTTP_HOST"] = sim_host
    env["SIM_HTTP_PORT"] = str(sim_port)
    env["SIM_UDP_HOST"] = os.getenv("SIM_UDP_HOST", "127.0.0.1")
    env["SIM_UDP_PORT"] = os.getenv("SIM_UDP_PORT", "9000")

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
        _wait_for_http_ready(f"{sim_http}/health", p, timeout_s=15.0)
        yield p
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

@pytest.fixture(autouse=True)
def reset_simulator(sim_api):
    """
    Ensure each test starts from a clean state.
    """
    sim_api.reset()
    yield
