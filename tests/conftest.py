import os
import subprocess
import time
import sys
import socket
import json
import platform
import uuid

from pathlib import Path
from datetime import datetime, timezone

import pytest
import httpx

from qaharness.config.settings import get_settings
from qaharness.api.client import SimApiClient
from qaharness.transport.udp import UdpClient, UdpEndpoint
from qaharness.transport.tcp import TcpClient, TcpEndpoint
from qaharness.reporting import SqlStore

REPO_ROOT = Path(__file__).resolve().parents[1]

_QA_SQL_STORE = None
_QA_RUN_ID = None
_QA_SEEN_CALL_REPORTS = set()
_QA_METRICS_SUMMARY = None

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _metrics_artifact_dir() -> Path:
    p = Path("artifacts") / "metrics"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _flatten_metrics_record(record: dict) -> list[tuple[str, float | int | None, str | None, dict]]:
    """
    convert structured metrics payloads into rows for perf_metrics
    keeps top-lvel context in tags and emits common numeric fields as rows
    """
    rows: list[tuple[str, float | int | None, str | None, dict]] = []

    base_tags = {
        "name": record.get("name"),
        "faults": record.get("faults"),
        "thresholds": record.get("thresholds"),
        "retry_policy": (record.get("retry") or {}).get("policy")
    }

    # generic top-level numeric values
    for k, v in record.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            rows.append((k, v, None, base_tags))

    # result block
    for k, v in (record.get("results") or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            unit = "ratio" if "rate" in k else None
            rows.append((f"results.{k}", v, unit, base_tags))

    # latency block
    for k, v in (record.get("latency_ms") or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            unit = "ms" if k not in ("count",) else None
            rows.append((f"latency.{k}", v, unit, base_tags))

    # retry block (aggregate stats)
    retry = record.get("retry") or {}
    for k, v in retry.items():
        if k == "policy":
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            unit = "s" if "sleep" in k else None
            rows.append((f"retry.{k}", v, unit, base_tags))
    return rows

def pytest_sessionstart(session):
    global _QA_SQL_STORE, _QA_RUN_ID, _QA_SEEN_CALL_REPORTS, _QA_METRICS_SUMMARY

    store = SqlStore()
    run_id = str(uuid.uuid4())

    git_sha = os.getenv("GITHUB_SHA") or os.getenv("CI_COMMIT_SHA")
    branch = os.getenv("GITHUB_REF_NAME") or os.getenv("CI_COMMIT_BRANCH")
    ci_job = os.getenv("GITHUB_JOB") or os.getenv("CI_JOB_NAME")

    store.start_run(
        run_id=run_id,
        started_at=_utc_now_iso(),
        git_sha=git_sha,
        branch=branch,
        ci_job=ci_job,
        os_name=platform.platform(),
        python_version=sys.version.split()[0],
    )

    _QA_SQL_STORE = store
    _QA_RUN_ID = run_id
    _QA_SEEN_CALL_REPORTS = set()

    # optional summary json (nice alongside DB)
    Path("artifacts").mkdir(exist_ok=True)
    session.config._qa_metrics_summary = {
        "run_id": run_id,
        "started_at": _utc_now_iso(),
        "tests": [],
        "db_path": str(store.db_path),
    }

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report):
    """
    Record one result row per test call phase
    """
    global _QA_SQL_STORE, _QA_RUN_ID, _QA_SEEN_CALL_REPORTS, _QA_METRICS_SUMMARY

    if report.when != "call":
        return

    store = _QA_SQL_STORE
    run_id = _QA_RUN_ID
    seen = _QA_SEEN_CALL_REPORTS
    summary = _QA_METRICS_SUMMARY

    if store is None or run_id is None or seen is None or summary is None:
        return

    # guard against duplicate processing
    key = (report.nodeid, report.when)
    if key in seen:
        return
    seen.add(key)

    outcome = "passed"
    if report.failed:
        outcome = "failed"
    elif report.skipped:
        outcome = "skipped"

    error_type = None
    error_message = None
    if report.failed and getattr(report, "longreprtext", None):
        text = report.longreprtext
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            error_message = lines[-1][:1000]
            # crude but useful extraction
            if ":" in lines[-1]:
                error_type = lines[-1].split(":", 1)[0][:200]

    store.record_test_result(
        run_id=run_id,
        nodeid=report.nodeid,
        outcome=outcome,
        duration_s=getattr(report, "duration", None),
        error_type=error_type,
        error_message=error_message,
    )

    # also append to JSON summary
    summary["tests"].append(
        {
            "nodeid": report.nodeid,
            "outcome": outcome,
            "duration_s": getattr(report, "duration", None),
        }
    )

def pytest_sessionfinish(session, exitstatus):
    global _QA_SQL_STORE, _QA_RUN_ID, _QA_METRICS_SUMMARY
    
    store = _QA_SQL_STORE
    run_id = _QA_RUN_ID
    summary = _QA_METRICS_SUMMARY

    if store is not None and run_id is not None:
        try:
            store.finish_run(run_id=run_id, finished_at=_utc_now_iso(), exit_status=int(exitstatus))
        finally:
            if summary is not None:
                summary["finished_at"] = _utc_now_iso()
                summary["existatus"] = int(exitstatus)
                Path("artifacts").mkdir(exist_ok=True)
                (Path("artifacts") / "metrics_summary.json").write_text(
                    json.dumps(summary, indent=2),
                    encoding="utf-8",
                )
            store.close()

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

    #p = subprocess.Popen(
    #    cmd,
    #    cwd=str(REPO_ROOT),
    #    env=env,
    #    stdout=subprocess.PIPE,
    #    stderr=subprocess.STDOUT,
    #    text=True,
    #    bufsize=1,
    #    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    #)

    creationflags = 0
    popen_kwargs = {}
    
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        popen_kwargs["creationflags"] = creationflags
    else:
        # start in a new session on  Unis so teardown can kill the whole process group if needed
        popen_kwargs["start_new_session"] = True
    
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **popen_kwargs,
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
    records structured metrics for a test:
    -   writes JSON artifacts to artifacts/metric/<test>.json
    -   writes falttened numeric metrics into SQLite perf_metrics

    """
    global _QA_SQL_STORE, _QA_RUN_ID

    start = time.time()
    records = []

    def record(payload: dict):
        records.append(payload)
        
        store = _QA_SQL_STORE
        run_id = _QA_RUN_ID
        if store is not None and run_id is not None:
            for metric_name, metric_value, unit, tags in _flatten_metrics_record(payload):
                store.record_metric(
                    run_id=run_id,
                    nodeid=request.node.nodeid,
                    metric_name=metric_name,
                    metric_value=metric_value,
                    unit=unit,
                    tags=tags,
                )
            # optional: persist retry event rows if payload includes detailed events
            retry = payload.get("retry") or {}
            for ev in retry.get("events", []) or []:
                # expected ev shape: {"request_name", "attempt", "sleep_s", "error"}
                try:
                    store.record_retry_event(
                        run_id=run_id,
                        nodeid=request.node.nodeid,
                        request_name=ev.get("request_name"),
                        attempt_number=int(ev.get("attempt", 0)),
                        sleep_s=float(ev.get("sleep_s", 0.0)),
                        exception_type=str(ev.get("error", "Exception")),
                    )
                except Exception:
                    # don't let telemetry break tests
                    pass
    yield record

    # write on teardown (even if test failed, if fixture teardown runs)
    test_id = request.node.nodeid.replace("/", "_").replace("::", "__")
    out = {
        "test_id": request.node.nodeid,
        "timestamp_epoch": start,
        "duration_s": time.time() - start,
        "records": records,
    }

    out_path = _metrics_artifact_dir() / f"{test_id}.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

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
